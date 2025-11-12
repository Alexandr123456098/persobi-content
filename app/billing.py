# -*- coding: utf-8 -*-
import sqlite3, time, os
DB_PATH = os.getenv("DB_PATH", "/root/persobi.db")

def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_billing():
    con = _connect()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        last_job_id INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    cur.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,
        prompt TEXT,
        src_path TEXT,
        preview_path TEXT,
        duration INT,
        sound INT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    cur.execute("""CREATE TABLE IF NOT EXISTS charges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        job_id INTEGER,
        amount INT,
        status TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    cur.execute("""CREATE TABLE IF NOT EXISTS tariffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        duration INT,
        sound INT,
        price INT,
        active INT DEFAULT 1
    );""")
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet_ops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        delta INT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );""")
    con.commit()
    con.close()

def ensure_user(user_id: int):
    con = _connect()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, balance) VALUES (?, 0)", (user_id,))
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
    cur.execute("INSERT INTO wallet_ops(user_id, delta, reason) VALUES (?,?,?)",
                (user_id, amount, reason))
    con.commit()
    con.close()

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
