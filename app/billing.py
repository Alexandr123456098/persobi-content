# -*- coding: utf-8 -*-
import sqlite3, os

DB_PATH = os.getenv("DB_PATH", "/root/persobi.db")

def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def _migrate(con):
    cur = con.cursor()
    # users
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        last_job_id INTEGER DEFAULT NULL,
        preview_free_used INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    # jobs
    cur.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        prompt TEXT,
        src_path TEXT,
        preview_path TEXT,
        duration REAL,
        sound INT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    # charges
    cur.execute("""CREATE TABLE IF NOT EXISTS charges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        job_id INTEGER,
        amount INT,
        status TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    # tariffs (не используется напрямую, но схема сохранена)
    cur.execute("""CREATE TABLE IF NOT EXISTS tariffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        duration REAL,
        sound INT,
        price INT,
        active INT DEFAULT 1
    );""")
    # wallet history
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet_ops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        delta INT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    # безопасно добавить недостающую колонку preview_free_used
    try:
        cur.execute("ALTER TABLE users ADD COLUMN preview_free_used INTEGER DEFAULT 0;")
    except Exception:
        pass
    con.commit()

def init_billing():
    con = _connect()
    _migrate(con)
    con.close()

def ensure_user(user_id: int):
    con = _connect()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, balance, preview_free_used) VALUES (?, 0, 0)", (user_id,))
    con.commit()
    con.close()

def get_balance(user_id: int) -> int:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else 0

def add_balance(user_id: int, amount: int, reason="Пополнение"):
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    cur.execute("INSERT INTO wallet_ops(user_id, delta, reason) VALUES (?,?,?)", (user_id, amount, reason))
    con.commit()
    con.close()

def _inc_free_used(user_id: int):
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET preview_free_used = preview_free_used + 1 WHERE user_id=?", (user_id,))
    con.commit()
    con.close()

def get_free_used(user_id: int) -> int:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT preview_free_used FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return int(row[0]) if row else 0

def can_take_free_preview(user_id: int) -> bool:
    return get_free_used(user_id) < 3

def charge(user_id: int, job_id: int, amount: int) -> bool:
    bal = get_balance(user_id)
    if bal < amount:
        return False
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
    cur.execute("INSERT INTO charges(user_id, job_id, amount, status) VALUES (?,?,?,?)",
                (user_id, job_id, amount, "captured"))
    con.commit()
    con.close()
    return True

def register_preview_and_charge(user_id: int, duration_sec, sound_flag: int) -> (bool, int):
    """
    Возвращает (ok, cost).
    ok=False и cost>0 — недостаточно средств, необходимо пополнение на cost.
    ok=True и cost==0 — списание не требуется (бесплатные превью).
    ok=True и cost>0 — успешно списали cost.
    """
    if can_take_free_preview(user_id):
        _inc_free_used(user_id)
        return True, 0

    from app.pricing import price
    cost = price(duration_sec, sound_flag)
    if charge(user_id, 0, cost):
        return True, cost
    else:
        return False, cost
