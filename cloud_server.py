import sqlite3
import os
import json
import uuid
import datetime
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求，因为本地执行端会在其他端口（如5000）请求云端

DB_PATH = 'cloud.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # 1. 权限配置表
    c.execute('''
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            max_domains INTEGER,
            max_terms INTEGER,
            allow_quiz BOOLEAN,
            quiz_daily_limit INTEGER,
            allow_dl_backup BOOLEAN
        )
    ''')
    # 2. 用户表
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            plan_id INTEGER,
            last_backup_date TEXT
        )
    ''')
    # 3. 卡密/解锁码表
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            key_code TEXT PRIMARY KEY,
            plan_id INTEGER,
            is_used BOOLEAN DEFAULT 0,
            used_by INTEGER DEFAULT NULL
        )
    ''')
    # 4. 远程备份表
    c.execute('''
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            backup_date TEXT,
            backup_data_json TEXT
        )
    ''')

    # 插入默认的权限记录
    plans_data = [
        (1, 'free', 1, 50, False, 0, False),
        (2, 'basic', -1, -1, True, 20, True),
        (3, 'pro', -1, -1, True, -1, True)
    ]
    for p in plans_data:
        c.execute('INSERT OR IGNORE INTO plans (id, name, max_domains, max_terms, allow_quiz, quiz_daily_limit, allow_dl_backup) VALUES (?, ?, ?, ?, ?, ?, ?)', p)

    # 插入一个测试用的 API Key：基础版 和 专业版
    c.execute('INSERT OR IGNORE INTO api_keys (key_code, plan_id) VALUES (?, ?)', ('BASIC-123', 2))
    c.execute('INSERT OR IGNORE INTO api_keys (key_code, plan_id) VALUES (?, ?)', ('PRO-888', 3))

    conn.commit()
    conn.close()

# ========== 鉴权与用户接口 ==========

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"code": 1, "msg": "用户名或密码不能为空"}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    try:
        pw_hash = generate_password_hash(password)
        # 默认分配 free 版本 (plan_id = 1)
        c.execute('INSERT INTO users (username, password_hash, plan_id) VALUES (?, ?, ?)', (username, pw_hash, 1))
        conn.commit()
        return jsonify({"code": 0, "msg": "注册成功，当前为免费版本。"})
    except sqlite3.IntegrityError:
        return jsonify({"code": 1, "msg": "注册失败，用户名已存在"}), 400
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    conn = get_db_connection()
    c = conn.cursor()
    user = c.execute('SELECT u.*, p.name as plan_name, p.max_domains, p.max_terms, p.allow_quiz, p.quiz_daily_limit, p.allow_dl_backup FROM users u JOIN plans p ON u.plan_id = p.id WHERE u.username = ?', (username,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password_hash'], password):
        # 简单返回基础信息和plan细节，实际应返回 Token
        return jsonify({
            "code": 0,
            "msg": "登录成功",
            "data": {
                "user_id": user['id'],
                "username": user['username'],
                "plan": {
                    "id": user['plan_id'],
                    "name": user['plan_name'],
                    "max_domains": user['max_domains'],
                    "max_terms": user['max_terms'],
                    "allow_quiz": user['allow_quiz'],
                    "quiz_daily_limit": user['quiz_daily_limit']
                }
            }
        })
    else:
        return jsonify({"code": 1, "msg": "用户名或密码错误"}), 401

@app.route('/api/auth/redeem', methods=['POST'])
def redeem():
    data = request.json
    user_id = data.get('user_id')
    key_code = data.get('key_code')

    if not user_id or not key_code:
        return jsonify({"code": 1, "msg": "缺少参数"}), 400

    conn = get_db_connection()
    c = conn.cursor()

    # 校验卡密
    api_key = c.execute('SELECT * FROM api_keys WHERE key_code = ? AND is_used = 0', (key_code,)).fetchone()
    if not api_key:
        conn.close()
        return jsonify({"code": 1, "msg": "无效或已使用的激活码"}), 400
    
    plan_id = api_key['plan_id']

    # 升级用户并核销卡密
    c.execute('UPDATE users SET plan_id = ? WHERE id = ?', (plan_id, user_id))
    c.execute('UPDATE api_keys SET is_used = 1, used_by = ? WHERE key_code = ?', (user_id, key_code))
    conn.commit()

    # 获取升级后的plan名
    plan_name = c.execute('SELECT name FROM plans WHERE id = ?', (plan_id,)).fetchone()['name']
    conn.close()

    return jsonify({"code": 0, "msg": f"兑换成功，您已升级为 {plan_name} 用户！", "plan_id": plan_id})

# ========== 远程服务接口 ==========

@app.route('/api/backup/upload', methods=['POST'])
def upload_backup():
    """ 本地端每天一次上传备份数据 """
    data = request.json
    user_id = data.get('user_id')
    backup_data = data.get('backup_data') # json 字符串或 dict

    if not user_id or not backup_data:
        return jsonify({"code": 1, "msg": "请求不完整"}), 400

    today_str = datetime.date.today().isoformat()
    conn = get_db_connection()
    c = conn.cursor()

    user = c.execute('SELECT last_backup_date, plan_id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"code": 1, "msg": "用户不存在"}), 404

    # 判断方案是否支持备份 (Pro / Basic 可能才支持)
    plan = c.execute('SELECT allow_dl_backup FROM plans WHERE id = ?', (user['plan_id'],)).fetchone()
    if not plan or not plan['allow_dl_backup']:
        conn.close()
        return jsonify({"code": 1, "msg": "当前版本不支持云端备份，请升级！"}), 403

    # 一天一次限制
    if user['last_backup_date'] == today_str:
        conn.close()
        return jsonify({"code": 1, "msg": "今天已经备份过了，请明天再来"}), 400

    json_str = json.dumps(backup_data) if isinstance(backup_data, dict) else backup_data
    
    # 插入备份
    c.execute('INSERT INTO backups (user_id, backup_date, backup_data_json) VALUES (?, ?, ?)', (user_id, today_str, json_str))
    # 更新最后备份时间
    c.execute('UPDATE users SET last_backup_date = ? WHERE id = ?', (today_str, user_id))
    conn.commit()
    conn.close()

    return jsonify({"code": 0, "msg": "云端备份成功！", "backup_date": today_str})

@app.route('/api/admin/generate_keys', methods=['POST'])
def generate_keys():
    """ 生成新卡密 """
    data = request.json
    plan_id = data.get('plan_id', 2)
    count = data.get('count', 5)

    conn = get_db_connection()
    c = conn.cursor()
    new_keys = []
    
    prefix = 'BASIC' if plan_id == 2 else ('PRO' if plan_id == 3 else 'KEY')
    for _ in range(count):
        k = f"{prefix}-{str(uuid.uuid4())[:8].upper()}"
        c.execute('INSERT INTO api_keys (key_code, plan_id) VALUES (?, ?)', (k, plan_id))
        new_keys.append(k)
        
    conn.commit()
    conn.close()
    
    return jsonify({"code": 0, "msg": "生成成功", "keys": new_keys})


if __name__ == '__main__':
    # 保证数据库存在
    init_db()
    # 绑定 5001 作为云端鉴权服务器
    app.run(host='0.0.0.0', port=5001, debug=True)
