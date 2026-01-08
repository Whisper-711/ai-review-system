import json


def insert_note(db, title, path):
    cur = db.cursor()
    cur.execute('INSERT INTO notes (title, path) VALUES (?, ?)', (title, path))
    db.commit()
    return cur.lastrowid


def insert_question_batch(db, note_id, questions):
    cur = db.cursor()

    # 读取当前库里已有的题干，用于简单去重（按 content 去重）
    cur.execute('SELECT content FROM questions')
    existing_contents = {row['content'] for row in cur.fetchall() if row['content']}

    for q in questions:
        content = q.get('content', '')
        if not content:
            continue
        if content in existing_contents:
            # 已存在相同题干，跳过以减少重复
            continue

        cur.execute(
            'INSERT INTO questions (note_id, knowledge_tag, q_type, content, options, answer, analysis, difficulty) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                note_id,
                q.get('knowledge_tag', ''),
                q.get('q_type', ''),
                content,
                json.dumps(q.get('options', []), ensure_ascii=False),
                q.get('answer', ''),
                q.get('analysis', ''),
                q.get('difficulty', ''),
            ),
        )
        existing_contents.add(content)

    db.commit()


def get_questions_by_knowledge(db, tags, limit, note_id=None, scope=None, q_type=None):
    """按知识点 / 模块 / 题型获取题目列表。

    - tags: 知识点标签列表，可为空。
    - limit: 返回题目数量上限。
    - note_id: 如果指定，仅从该模块的题目中抽取。
    - scope: 可选 'latest' 表示从最新模块中抽题；其他值或为空则不限制模块。
    - q_type: 可选 'single_choice' / 'short_answer'，否则不过滤题型。
    """

    cur = db.cursor()

    # 计算模块范围
    resolved_note_id = None
    if note_id is not None:
        resolved_note_id = note_id
    elif scope == 'latest':
        cur.execute('SELECT id FROM notes ORDER BY created_at DESC LIMIT 1')
        row = cur.fetchone()
        if row:
            resolved_note_id = row['id']

    # 构造 SQL
    sql = 'SELECT * FROM questions WHERE 1=1'
    params = []

    if resolved_note_id is not None:
        sql += ' AND note_id = ?'
        params.append(resolved_note_id)

    if tags:
        placeholders = ','.join('?' for _ in tags)
        sql += f' AND knowledge_tag IN ({placeholders})'
        params.extend(tags)

    if q_type in ('single_choice', 'short_answer'):
        sql += ' AND q_type = ?'
        params.append(q_type)

    # 随机顺序抽题，增强练习多样性
    sql += ' ORDER BY RANDOM() LIMIT ?'
    params.append(limit)

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    return [_row_to_question_dict(r) for r in rows]


def insert_answer(db, question_id, user_answer, is_correct):
    cur = db.cursor()
    cur.execute(
        'INSERT INTO user_answers (question_id, user_answer, is_correct) VALUES (?, ?, ?)',
        (question_id, user_answer, 1 if is_correct else 0),
    )
    db.commit()


def get_wrong_questions(db, limit):
    cur = db.cursor()
    cur.execute(
        '''SELECT q.* FROM questions q
           JOIN user_answers a ON q.id = a.question_id
           WHERE a.is_correct = 0
           GROUP BY q.id
           ORDER BY MAX(a.created_at) DESC
           LIMIT ?''',
        (limit,),
    )
    rows = cur.fetchall()
    return [_row_to_question_dict(r) for r in rows]


def get_stats_overview(db):
    cur = db.cursor()

    cur.execute('SELECT COUNT(*) FROM user_answers')
    total_answers = cur.fetchone()[0]

    cur.execute('SELECT COUNT(*) FROM user_answers WHERE is_correct = 1')
    correct_answers = cur.fetchone()[0]

    return {
        'total_answers': total_answers,
        'correct_answers': correct_answers,
        'accuracy': (correct_answers / total_answers) if total_answers else 0,
        # 按周聚合答题情况，week 形如 "2025-01"（年第几周）
        'by_week': get_stats_by_week(db),
    }


def get_stats_by_week(db):
    """按周统计答题量与正确率。"""

    cur = db.cursor()
    cur.execute(
        '''SELECT strftime('%Y-%W', created_at) AS week,
                  COUNT(*) AS total,
                  SUM(is_correct) AS correct
           FROM user_answers
           GROUP BY week
           ORDER BY week'''
    )
    rows = cur.fetchall()
    result = []
    for r in rows:
        total = r['total'] or 0
        correct = r['correct'] or 0
        accuracy = (correct / total) if total else 0
        result.append(
            {
                'week': r['week'],
                'total': total,
                'correct': correct,
                'accuracy': accuracy,
            }
        )
    return result


def get_question_by_id(db, question_id):
    cur = db.cursor()
    cur.execute('SELECT * FROM questions WHERE id = ?', (question_id,))
    row = cur.fetchone()
    if not row:
        return None
    return _row_to_question_dict(row)


def delete_note(db, note_id):
    """删除指定笔记模块及其题目和作答记录。"""

    cur = db.cursor()

    # 先删除关联的作答记录
    cur.execute('SELECT id FROM questions WHERE note_id = ?', (note_id,))
    q_ids = [row['id'] for row in cur.fetchall()]
    if q_ids:
        placeholders = ','.join('?' for _ in q_ids)
        cur.execute(f'DELETE FROM user_answers WHERE question_id IN ({placeholders})', tuple(q_ids))

    # 再删除题目和笔记
    cur.execute('DELETE FROM questions WHERE note_id = ?', (note_id,))
    cur.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    db.commit()


def _row_to_question_dict(row):
    return {
        'id': row['id'],
        'note_id': row['note_id'],
        'knowledge_tag': row['knowledge_tag'],
        'q_type': row['q_type'],
        'content': row['content'],
        'options': json.loads(row['options'] or '[]'),
        'answer': row['answer'],
        'analysis': row['analysis'],
        'difficulty': row['difficulty'],
    }
