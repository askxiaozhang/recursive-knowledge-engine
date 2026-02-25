from flask import Flask, request, jsonify, render_template, session
import os
import sqlite3
import requests
import json
import datetime

app = Flask(__name__)
app.secret_key = "local_client_secret_key"  # 用于session

CLOUD_SERVER_URL = "http://127.0.0.1:5001"
LOCAL_DB_PATH = "local.db"

# ==========================================
# 1. 本地数据库初始化
# ==========================================
def get_local_db():
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_local_db():
    conn = get_local_db()
    c = conn.cursor()
    # 领域表
    c.execute('''CREATE TABLE IF NOT EXISTS domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        created_at TEXT
    )''')
    # 知识点表 (术语)
    c.execute('''CREATE TABLE IF NOT EXISTS terms (
        id TEXT PRIMARY KEY,
        label TEXT,
        group_type TEXT
    )''')
    # 关系表
    c.execute('''CREATE TABLE IF NOT EXISTS relations (
        id TEXT PRIMARY KEY,
        source TEXT,
        target TEXT,
        label TEXT
    )''')
    # 历史记录
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        created_at TEXT
    )''')
    # 出题记录
    c.execute('''CREATE TABLE IF NOT EXISTS quizzes_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_local_db()

# ==========================================
# 2. 会话权限辅助函数
# ==========================================
def get_current_user():
    return session.get("user")

def get_user_counts():
    conn = get_local_db()
    c = conn.cursor()
    domains = c.execute('SELECT COUNT(*) FROM domains').fetchone()[0]
    terms = c.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
    today = datetime.date.today().isoformat()
    today_quizzes = c.execute("SELECT COUNT(*) FROM quizzes_log WHERE created_at LIKE ?", (today + "%",)).fetchone()[0]
    conn.close()
    return {
        "domains": domains,
        "terms": terms,
        "today_quizzes": today_quizzes
    }

# ==========================================
# 3. 页面路由
# ==========================================
@app.route("/")
def index():
    user = get_current_user()
    if not user:
        # 如果未登录，只传默认的展示态
        return render_template("index.html", user=None, counts={"domains":0, "today_quizzes":0})
    
    counts = get_user_counts()
    return render_template("index.html", user=user, counts=counts)

@app.route("/chat")
def chat_page():
    user = get_current_user()
    if not user:
        return "请先在首页登录！", 401
    
    if user['plan']['id'] == 1: # 免费版限制
         # 只要登录了允许进入体验，由内层接口控制
         pass
         
    return render_template("chat.html", user=user)

# ==========================================
# 4. 代理云端鉴权接口
# ==========================================
@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    try:
        resp = requests.post(f"{CLOUD_SERVER_URL}/api/auth/register", json=request.json, timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"code": 1, "msg": "连接云端服务器失败"}), 500

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    try:
        resp = requests.post(f"{CLOUD_SERVER_URL}/api/auth/login", json=request.json, timeout=5)
        data = resp.json()
        if data.get('code') == 0:
            # 登录成功，将云端返回的用户权限保存在本地 session
            session['user'] = data['data']
        return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"code": 1, "msg": "连接云端服务器失败"}), 500

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.pop('user', None)
    return jsonify({"code": 0, "msg": "已退出登录"})

@app.route("/api/auth/redeem", methods=["POST"])
def auth_redeem():
    user = get_current_user()
    if not user:
        return jsonify({"code": 1, "msg": "未登录"}), 401
    try:
        payload = {"user_id": user['user_id'], "key_code": request.json.get('key_code')}
        resp = requests.post(f"{CLOUD_SERVER_URL}/api/auth/redeem", json=payload, timeout=5)
        data = resp.json()
        if data.get('code') == 0:
            # 兑换成功，重新拉取用户信息或直接修改 session (这里简单处理为让用户重新登录，或者直接更新 plan_id, 这里选择直接更新部分)
            # 最好是要求用户重新登录，简单起见我们提示重新登录
            session.pop('user', None) 
            data['msg'] += " 请重新登录以刷新权限。"
        return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"code": 1, "msg": "连接云端服务器失败"}), 500

@app.route("/api/backup/upload", methods=["POST"])
def backup_upload():
    user = get_current_user()
    if not user:
        return jsonify({"code": 1, "msg": "未登录"}), 401
    
    # 提取本地所有数据
    conn = get_local_db()
    c = conn.cursor()
    domains = [dict(row) for row in c.execute('SELECT * FROM domains').fetchall()]
    terms = [dict(row) for row in c.execute('SELECT * FROM terms').fetchall()]
    relations = [dict(row) for row in c.execute('SELECT * FROM relations').fetchall()]
    chat_history = [dict(row) for row in c.execute('SELECT * FROM chat_history').fetchall()]
    conn.close()
    
    backup_data = {
        "domains": domains,
        "terms": terms,
        "relations": relations,
        "chat_history": chat_history
    }
    
    payload = {
        "user_id": user['user_id'],
        "backup_data": backup_data
    }
    
    try:
        resp = requests.post(f"{CLOUD_SERVER_URL}/api/backup/upload", json=payload, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"code": 1, "msg": "连接云端服务器备份失败"}), 500

# ==========================================
# 5. 本地核心业务接口 (受 session 权限控制)
# ==========================================
@app.route("/api/domain/create", methods=["POST"])
def create_domain():
    user = get_current_user()
    if not user:
        return jsonify({"code": 1, "msg": "请先登录"}), 401
        
    plan = user['plan']
    counts = get_user_counts()

    if plan['max_domains'] != -1 and counts['domains'] >= plan['max_domains']:
        return jsonify({"code": 1, "msg": f"当前版本最多创建{plan['max_domains']}个领域，请升级解锁！"}), 403

    domain_name = request.json.get("name", "未命名领域")
    
    conn = get_local_db()
    c = conn.cursor()
    c.execute('INSERT INTO domains (name, created_at) VALUES (?, ?)', (domain_name, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    return jsonify({"code": 0, "domain_id": c.lastrowid, "msg": "领域创建成功"})

@app.route("/api/quiz/generate", methods=["POST"])
def gen_quiz():
    user = get_current_user()
    if not user:
        return jsonify({"code": 1, "msg": "请先登录"}), 401
        
    plan = user['plan']
    if not plan['allow_quiz']:
        return jsonify({"code": 1, "msg": "当前版本支持出题，请升级！"}), 403

    counts = get_user_counts()
    if plan['quiz_daily_limit'] != -1 and counts['today_quizzes'] >= plan['quiz_daily_limit']:
        return jsonify({"code": 1, "msg": f"今日额度已满 ({plan['quiz_daily_limit']}题)，请升级专业版解锁无限出题！"}), 403

    conn = get_local_db()
    c = conn.cursor()
    c.execute('INSERT INTO quizzes_log (created_at) VALUES (?)', (datetime.datetime.now().isoformat(),))
    conn.commit()
    conn.close()

    return jsonify({"code": 0, "quiz": "1. 解释图谱的作用？\n2. SQLite与MySQL对比？", "msg": "出题成功！"})

@app.route("/api/chat", methods=["POST"])
def chat_api():
    user = get_current_user()
    if not user:
        return jsonify({"code": 1, "msg": "请先登录"}), 401

    data = request.json
    user_msg = data.get("message", "")
    
    # 本地保存用户消息
    conn = get_local_db()
    c = conn.cursor()
    now_str = datetime.datetime.now().isoformat()
    c.execute('INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)', ('user', user_msg, now_str))
    
    # 模拟AI生成逻辑
    if "Transformer" in user_msg or "transformer" in user_msg.lower():
        reply = "Transformer是一个基于自注意力机制的序列模型，被广泛应用于NLP领域。"
        entities = [
            {"id": "Transformer", "label": "Transformer", "group": "model"},
            {"id": "Self-Attention", "label": "自注意力机制", "group": "concept"}
        ]
        relations = [
            {"from": "Transformer", "to": "Self-Attention", "label": "基于起"}
        ]
    else:
        reply = f"我已经收到了你的问题：'{user_msg}'。我会分析其中的专业术语并在左侧构建知识图谱。"
        entities = [
            {"id": "UserQuery", "label": "用户问题", "group": "concept"},
            {"id": "KnowledgeGraph", "label": "知识图谱", "group": "domain"}
        ]
        relations = [
            {"from": "UserQuery", "to": "KnowledgeGraph", "label": "更新"}
        ]

    # 保存 AI 消息
    c.execute('INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)', ('ai', reply, datetime.datetime.now().isoformat()))
    
    # 解析并保存实体和关系到本地 local.db（检查上限）
    plan = user['plan']
    # 简单计算当前知识点数量
    current_terms_count = c.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
    
    saved_entities = 0
    for ent in entities:
        if plan['max_terms'] != -1 and current_terms_count + saved_entities >= plan['max_terms']:
            reply += "\n\n[系统提示] 知识点存储已达上限，停止记录新节点。请升级版本。"
            break
        
        # 插入或忽略
        try:
            c.execute('INSERT OR IGNORE INTO terms (id, label, group_type) VALUES (?, ?, ?)', (ent['id'], ent['label'], ent['group']))
            saved_entities += 1
        except Exception:
            pass
            
    for rel in relations:
        rel_id = f"{rel['from']}-{rel['to']}-{rel['label']}"
        try:
            c.execute('INSERT OR IGNORE INTO relations (id, source, target, label) VALUES (?, ?, ?, ?)', (rel_id, rel['from'], rel['to'], rel['label']))
        except Exception:
            pass

    conn.commit()
    conn.close()

    return jsonify({
        "code": 0,
        "reply": reply,
        "entities": entities,
        "relations": relations
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
