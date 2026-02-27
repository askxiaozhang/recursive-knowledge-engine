from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import os
import sqlite3
import json
import datetime
from dotenv import load_dotenv
from bot import Bot
from database import get_local_db
load_dotenv()

bot = Bot()

app = Flask(__name__)
app.secret_key = "local_client_secret_key"  # 用于session

# ==========================================
# 2. 会话权限辅助函数 (已改为纯本地)
# ==========================================
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
# 3. 页面数据辅助函数
# ==========================================
def get_app_data(domain_id=None):
    conn = get_local_db()
    c = conn.cursor()
    
    if not domain_id:
        domain = c.execute("SELECT id FROM domains ORDER BY id DESC LIMIT 1").fetchone()
        if domain:
            domain_id = domain["id"]
        else:
            c.execute('INSERT INTO domains (name, created_at) VALUES (?, ?)', ("默认领域", datetime.datetime.now().isoformat()))
            domain_id = c.lastrowid
            conn.commit()

    terms_db = c.execute('SELECT * FROM terms WHERE domain_id = ?', (domain_id,)).fetchall()
    relations_db = c.execute('SELECT * FROM relations WHERE domain_id = ?', (domain_id,)).fetchall()
    chat_history_db = c.execute('SELECT role, content FROM chat_history WHERE domain_id = ? ORDER BY id ASC', (domain_id,)).fetchall()
    
    all_domains_db = c.execute('SELECT id, name FROM domains ORDER BY id DESC').fetchall()
    all_domains = [{"id": d["id"], "name": d["name"]} for d in all_domains_db]

    conn.close()

    initial_nodes = []
    for t in terms_db:
        initial_nodes.append({"id": str(t["id"]), "label": t["label"], "group": t["group_type"]})

    initial_edges = []
    for r in relations_db:
        initial_edges.append({
            "id": r["id"],
            "from": str(r["source"]),
            "to": str(r["target"]),
            "label": r["label"]
        })
        
    chat_history = []
    for msg in chat_history_db:
        chat_history.append({"role": msg["role"], "content": msg["content"]})
    
    return initial_nodes, initial_edges, chat_history, all_domains, domain_id

# ==========================================
# 4. 页面路由
# ==========================================
@app.route("/")
def index():
    domain_id = request.args.get('domain_id', type=int)
    counts = get_user_counts()
    initial_nodes, initial_edges, chat_history, all_domains, current_domain_id = get_app_data(domain_id)
    
    return render_template("index.html", 
                           counts=counts, 
                           initial_nodes=initial_nodes, 
                           initial_edges=initial_edges, 
                           chat_history=chat_history,
                           all_domains=all_domains,
                           current_domain_id=current_domain_id)

@app.route("/chat")
def chat_page():
    return index()

# ==========================================
# 4. 本地核心业务接口 (已移除登录)
# ==========================================
@app.route("/api/domain/create", methods=["POST"])
def create_domain():

    domain_name = request.json.get("name", "未命名领域")
    
    conn = get_local_db()
    c = conn.cursor()
    c.execute('INSERT INTO domains (name, created_at) VALUES (?, ?)', (domain_name, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    return jsonify({"code": 0, "domain_id": c.lastrowid, "msg": "领域创建成功"})

@app.route("/api/quiz/generate", methods=["POST"])
def gen_quiz():
    counts = get_user_counts()
    if counts['today_quizzes'] >= 5:
        return jsonify({"code": 1, "msg": "今日免费额度已满 (5题)！"}), 403

    data = request.json or {}
    node_label = data.get("node_label")
    api_key = data.get("api_key")
    base_url = data.get("base_url")
    model = data.get("model")

    if not node_label:
        return jsonify({"code": 1, "msg": "未提供节点信息"}), 400

    conn = get_local_db()
    c = conn.cursor()
    c.execute('INSERT INTO quizzes_log (created_at) VALUES (?)', (datetime.datetime.now().isoformat(),))
    conn.commit()
    conn.close()

    try:
        prompt = f"请针对知识节点“{node_label}”生成一道或两道递归思考题，要求能够引导学习者深入理解该概念或其关联机制，题目内容简明扼要，直接输出题目，不要给出答案。"
        quiz_content = bot.chat(
            prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            model=model
        )
    except Exception as e:
        print(f"出题失败: {e}")
        quiz_content = f"关于【{node_label}】的思考题：\n1. 它的核心机制是什么？\n2. 它是为了解决什么问题而产生的？"

    return jsonify({"code": 0, "quiz": quiz_content, "msg": "出题成功！"})

@app.route("/api/chat/clear", methods=["POST"])
def clear_chat():
    data = request.json or {}
    domain_id = data.get("domain_id")
    
    if not domain_id:
        return jsonify({"code": 1, "msg": "缺失 domain_id 参数"})

    conn = get_local_db()
    c = conn.cursor()
    c.execute('DELETE FROM chat_history WHERE domain_id = ?', (domain_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"code": 0, "msg": "已清空学习上下文"})

@app.route("/api/notes/<node_id>", methods=["GET"])
def get_notes(node_id):
    domain_id = request.args.get("domain_id")
    conn = get_local_db()
    c = conn.cursor()
    # 如果节点在不同领域可能重复，可以按 domain_id 过滤。但当前 id 可能是唯一的。
    # 为了保险，也查询匹配 domain_id 或者不管。我们假设节点 id 全局唯一也可以，但最好按 domain_id 隔离。
    if domain_id:
        row = c.execute('SELECT notes FROM terms WHERE id = ? AND domain_id = ?', (node_id, domain_id)).fetchone()
    else:
        row = c.execute('SELECT notes FROM terms WHERE id = ?', (node_id,)).fetchone()
    conn.close()
    
    notes = row["notes"] if row and row["notes"] else ""
    return jsonify({"code": 0, "notes": notes})

@app.route("/api/notes/<node_id>", methods=["POST"])
def save_notes(node_id):
    
    data = request.json
    notes = data.get("notes", "")
    domain_id = data.get("domain_id")
    
    conn = get_local_db()
    c = conn.cursor()
    if domain_id:
        c.execute('UPDATE terms SET notes = ? WHERE id = ? AND domain_id = ?', (notes, node_id, domain_id))
    else:
        c.execute('UPDATE terms SET notes = ? WHERE id = ?', (notes, node_id))
    conn.commit()
    conn.close()
    
    return jsonify({"code": 0, "msg": "笔记已保存"})

@app.route("/api/chat", methods=["POST"])
def chat_api():

    data = request.json
    user_msg = data.get("message", "")
    domain_id = data.get("domain_id")
    
    if not domain_id:
        return jsonify({"code": 1, "msg": "缺失 domain_id"}), 400
    
    # 本地保存用户消息
    conn = get_local_db()
    c = conn.cursor()
    now_str = datetime.datetime.now().isoformat()
    c.execute('INSERT INTO chat_history (role, content, created_at, domain_id) VALUES (?, ?, ?, ?)', ('user', user_msg, now_str, domain_id))
    conn.commit()
    conn.close()
    
    def generate():
        response_buffer = ""
        try:
            conn_temp = get_local_db()
            c_temp = conn_temp.cursor()
            existing_terms = [{"id": row["id"], "label": row["label"]} for row in c_temp.execute('SELECT id, label FROM terms WHERE domain_id = ?', (domain_id,)).fetchall()]
            conn_temp.close()
            
            existing_terms_str = json.dumps(existing_terms, ensure_ascii=False)
            
            sys_prompt = f"""你是一个智能知识图谱小助手。请回答用户的问题，并从你的回答中提取核心实体和他们之间的关系。
请必须以合法的JSON格式返回，不要包含其他文本（不要使用```json），且JSON的结构必须严谨，如下：
{{"reply": "你的回答内容", "entities": [{{"id": "唯一标识", "label": "显示名", "group": "层次分类"}}], "relations": [{{"from": "实体A的id", "to": "实体B的id", "label": "关系名"}}]}}

【重要指示】
为了实现3层渐进式信息架构展示，你需要对提取出的实体通过"group"字段进行分类。
"group" 的值必须且只能是以下三者之一：
1. "core"：核心概念（第一层框架，如用户当前询问的主题实体，通常只能有1个）
2. "primary"：关键维度节点（第一层框架，如“核心组件”、“解决问题”、“应用场景”、“提出背景”等，最多3-5个）
3. "detail"：二级及以下补充节点（第二层深度视图，如具体的参数、子技术名词、人名、文献等）

构建 relations 时，优先构建 core 与 primary 之间的连线，以及 primary 与其对应 details 之间的连线。

为了保持专业术语和关系的一致性，请尽量复用以下现有的实体ID：
{existing_terms_str}"""

            api_key = data.get("api_key")
            base_url = data.get("base_url")
            model_name = data.get("model")
            
            for chunk in bot.chat_stream(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg}
                ],
                api_key=api_key,
                base_url=base_url,
                model=model_name
            ):
                response_buffer += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                
            print(f"DEBUG: response_buffer length: {len(response_buffer)}")
            clean_token = response_buffer.strip()
            if clean_token.startswith("```"):
                lines = clean_token.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_token = "\n".join(lines).strip()
            
            if not clean_token:
                raise ValueError("模型返回了空内容")

            llm_data = json.loads(clean_token)
            reply = llm_data.get("reply", "我无法理解该问题。")
            entities = llm_data.get("entities", [])
            relations = llm_data.get("relations", [])
            
            for ent in entities:
                if "id" in ent:
                    ent["id"] = str(ent["id"])
            for rel in relations:
                if "from" in rel:
                    rel["from"] = str(rel["from"])
                if "to" in rel:
                    rel["to"] = str(rel["to"])
        except Exception as e:
            reply = f"大模型请求或解析失败: {str(e)}"
            entities = []
            relations = []
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        try:
            conn2 = get_local_db()
            c2 = conn2.cursor()
            c2.execute('INSERT INTO chat_history (role, content, created_at, domain_id) VALUES (?, ?, ?, ?)', ('ai', reply, datetime.datetime.now().isoformat(), domain_id))
            
            for ent in entities:
                try:
                    c2.execute('INSERT OR IGNORE INTO terms (id, label, group_type, domain_id) VALUES (?, ?, ?, ?)', (ent['id'], ent['label'], ent['group'], domain_id))
                except Exception:
                    pass
                    
            for rel in relations:
                rel_id = f"{rel['from']}-{rel['to']}-{rel['label']}-{domain_id}"
                try:
                    c2.execute('INSERT OR IGNORE INTO relations (id, source, target, label, domain_id) VALUES (?, ?, ?, ?, ?)', (rel_id, rel['from'], rel['to'], rel['label'], domain_id))
                except Exception:
                    pass

            conn2.commit()
            conn2.close()

        except Exception as e:
            print(f"入库报错: {e}")

        final_data = {
            "type": "done",
            "reply_final": reply,
            "entities": entities,
            "relations": relations
        }
        yield f"data: {json.dumps(final_data)}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True, port=5002)
