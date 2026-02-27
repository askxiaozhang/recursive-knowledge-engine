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
        id TEXT,
        label TEXT,
        group_type TEXT,
        notes TEXT,
        domain_id INTEGER,
        PRIMARY KEY (id, domain_id)
    )''')
    # 关系表
    c.execute('''CREATE TABLE IF NOT EXISTS relations (
        id TEXT,
        source TEXT,
        target TEXT,
        label TEXT,
        domain_id INTEGER,
        PRIMARY KEY (id, domain_id)
    )''')
    # 历史记录
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        created_at TEXT,
        domain_id INTEGER
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

    try:
        c.execute("ALTER TABLE terms ADD COLUMN domain_id INTEGER")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE terms SET domain_id = 1 WHERE domain_id IS NULL")
    
    # 迁移为联合主键 (Composite Primary Key)
    info = c.execute("PRAGMA table_info(terms)").fetchall()
    domain_pk = any(col["name"] == "domain_id" and col["pk"] > 0 for col in info)
    if not domain_pk:
        c.execute('''CREATE TABLE IF NOT EXISTS terms_new (
            id TEXT,
            label TEXT,
            group_type TEXT,
            notes TEXT,
            domain_id INTEGER,
            PRIMARY KEY (id, domain_id)
        )''')
        c.execute("INSERT OR IGNORE INTO terms_new SELECT id, label, group_type, notes, domain_id FROM terms")
        c.execute("DROP TABLE terms")
        c.execute("ALTER TABLE terms_new RENAME TO terms")

    try:
        c.execute("ALTER TABLE relations ADD COLUMN domain_id INTEGER")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE relations SET domain_id = 1 WHERE domain_id IS NULL")

    info_r = c.execute("PRAGMA table_info(relations)").fetchall()
    domain_pk_r = any(col["name"] == "domain_id" and col["pk"] > 0 for col in info_r)
    if not domain_pk_r:
        c.execute('''CREATE TABLE IF NOT EXISTS relations_new (
            id TEXT,
            source TEXT,
            target TEXT,
            label TEXT,
            domain_id INTEGER,
            PRIMARY KEY (id, domain_id)
        )''')
        c.execute("INSERT OR IGNORE INTO relations_new SELECT id, source, target, label, domain_id FROM relations")
        c.execute("DROP TABLE relations")
        c.execute("ALTER TABLE relations_new RENAME TO relations")

    try:
        c.execute("ALTER TABLE chat_history ADD COLUMN domain_id INTEGER")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE chat_history SET domain_id = 1 WHERE domain_id IS NULL")

    conn.commit()
    conn.close()

init_local_db()
