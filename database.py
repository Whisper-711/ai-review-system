import os
import sqlite3
from flask import g

DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        '''CREATE TABLE IF NOT EXISTS notes (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               path TEXT NOT NULL,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )'''
    )

    c.execute(
        '''CREATE TABLE IF NOT EXISTS questions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               note_id INTEGER,
               knowledge_tag TEXT,
               q_type TEXT,
               content TEXT,
               options TEXT,
               answer TEXT,
               analysis TEXT,
               difficulty TEXT,
               case_material TEXT DEFAULT '',
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )'''
    )

    c.execute(
        '''CREATE TABLE IF NOT EXISTS user_answers (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               question_id INTEGER,
               user_answer TEXT,
               is_correct INTEGER,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )'''
    )

    # 迁移：为旧表加 case_material 列（幂等）
    try:
        c.execute('ALTER TABLE questions ADD COLUMN case_material TEXT DEFAULT ""')
    except Exception:
        pass  # 列已存在

    # 索引
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_questions_q_type ON questions(q_type)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_questions_knowledge_tag ON questions(knowledge_tag)')
    except Exception:
        pass

    conn.commit()
    conn.close()
