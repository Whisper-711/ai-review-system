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

    conn.commit()
    conn.close()
