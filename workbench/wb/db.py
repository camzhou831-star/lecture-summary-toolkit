"""SQLite 任务表。一个任务 = 一个来源(链接或文件)走完 拿稿 → 整理 → 总结 → 核对。

每次操作开一个新连接(后台线程和请求线程各用各的),WAL 模式下读写互不挡。
"""
import json
import os
import sqlite3
import threading
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    kind        TEXT NOT NULL,            -- youtube / bilibili / local
    source      TEXT NOT NULL,            -- 链接,或本地文件路径
    vid         TEXT,                     -- 平台作品 id 或文件名
    title       TEXT,
    lang        TEXT NOT NULL DEFAULT 'auto',   -- 视频语言(转写 / 字幕语言)
    out_lang    TEXT NOT NULL DEFAULT 'zh',     -- 总结语言
    template    TEXT NOT NULL DEFAULT 'course', -- 模板:课程总结
    status      TEXT NOT NULL DEFAULT 'queued', -- queued / running / done / failed
    stage       TEXT,                     -- fetch / prepare / summarize / check
    message     TEXT,                     -- 给人看的一句话进度或错误
    log         TEXT NOT NULL DEFAULT '',
    timings     TEXT NOT NULL DEFAULT '{}',     -- {阶段: 秒}
    check_ok    INTEGER,                  -- check_summary 是否通过
    check_report TEXT,
    meta        TEXT NOT NULL DEFAULT '{}'      -- 作品数据(标题、作者、时长、来源精度…)
);
"""
_lock = threading.Lock()


def db_path():
    return os.path.join(config.DATA, "workbench.db")


def connect():
    os.makedirs(config.DATA, exist_ok=True)
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with connect() as c:
        c.executescript(SCHEMA)
        # 上次关掉时还在跑的任务:重新排队(每一步都能从已有产物接着做)
        c.execute("UPDATE tasks SET status='queued', message='上次未完成,重新排队' WHERE status='running'")


def row_dict(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("timings", "meta"):
        d[k] = json.loads(d[k] or "{}")
    return d


def create(kind, source, vid, lang="auto", out_lang="zh", template="course", title=None):
    now = time.time()
    with _lock, connect() as c:
        cur = c.execute(
            "INSERT INTO tasks (created_at, updated_at, kind, source, vid, title, lang, out_lang, template, message) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now, now, kind, source, vid, title, lang, out_lang, template, "排队中"))
        return cur.lastrowid


def get(task_id):
    with connect() as c:
        return row_dict(c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def list_all(limit=100):
    with connect() as c:
        rows = c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [row_dict(r) for r in rows]


def update(task_id, **fields):
    if not fields:
        return
    for k in ("timings", "meta"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, connect() as c:
        c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))


def append_log(task_id, text):
    with _lock, connect() as c:
        c.execute("UPDATE tasks SET log = log || ?, updated_at=? WHERE id=?", (text.rstrip("\n") + "\n", time.time(), task_id))


def next_queued():
    with connect() as c:
        r = c.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    return r["id"] if r else None


def claim_next():
    """取最早排队的任务并标成 running(同一个任务不会被两个线程拿到)→ 任务号或 None"""
    with _lock, connect() as c:
        r = c.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE tasks SET status='running', message='开始处理…' WHERE id=?", (r["id"],))
    return r["id"]


def delete(task_id):
    with _lock, connect() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
