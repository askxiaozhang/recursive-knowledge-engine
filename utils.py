import datetime
from flask import session
from database import get_local_db

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
