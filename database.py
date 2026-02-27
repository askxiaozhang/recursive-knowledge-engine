import sqlite3
from config import Config

def get_local_db():
    conn = sqlite3.connect(Config.LOCAL_DB_PATH)
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
        group_type TEXT,
        notes TEXT
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
    
    # 检查并添加 notes 列（Migration 处理）
    try:
        c.execute("ALTER TABLE terms ADD COLUMN notes TEXT")
    except sqlite3.OperationalError:
        # 已经存在则忽略
        pass

    conn.commit()
    conn.close()

init_local_db()
