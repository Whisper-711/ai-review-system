import json
import math


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
            'INSERT INTO questions (note_id, knowledge_tag, q_type, content, options, answer, analysis, difficulty, case_material) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                note_id,
                q.get('knowledge_tag', ''),
                q.get('q_type', ''),
                content,
                json.dumps(q.get('options', []), ensure_ascii=False),
                q.get('answer', ''),
                q.get('analysis', ''),
                q.get('difficulty', ''),
                q.get('case_material', ''),
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

    if q_type in ('single_choice', 'short_answer', 'fill_blank'):
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


def search_questions(db, q='', q_type='', difficulty='', knowledge_tag='', note_id=None, page=1, per_page=20):
    """全文搜索 + 高级筛选，支持分页。"""
    cur = db.cursor()
    conditions = []
    params = []

    if q:
        like = f'%{q}%'
        conditions.append('(content LIKE ? OR answer LIKE ? OR analysis LIKE ? OR case_material LIKE ? OR knowledge_tag LIKE ?)')
        params.extend([like, like, like, like, like])

    if q_type:
        conditions.append('q_type = ?')
        params.append(q_type)

    if difficulty:
        conditions.append('difficulty = ?')
        params.append(difficulty)

    if knowledge_tag:
        conditions.append('knowledge_tag = ?')
        params.append(knowledge_tag)

    if note_id is not None:
        conditions.append('note_id = ?')
        params.append(note_id)

    where_clause = ' AND '.join(conditions) if conditions else '1=1'
    count_sql = f'SELECT COUNT(*) FROM questions WHERE {where_clause}'
    cur.execute(count_sql, tuple(params))
    total = cur.fetchone()[0]

    offset = (page - 1) * per_page
    data_sql = f'SELECT * FROM questions WHERE {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?'
    cur.execute(data_sql, tuple(params) + (per_page, offset))
    rows = cur.fetchall()

    return {
        'questions': [_row_to_question_dict(r) for r in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': math.ceil(total / per_page) if per_page else 0,
    }


def get_stats_by_tag(db):
    """按知识点标签统计答题情况，返回各标签的答题数、正确数、正确率。"""
    cur = db.cursor()
    cur.execute(
        '''SELECT q.knowledge_tag,
                  COUNT(a.id) AS total,
                  SUM(a.is_correct) AS correct
           FROM questions q
           JOIN user_answers a ON q.id = a.question_id
           WHERE q.knowledge_tag != ''
           GROUP BY q.knowledge_tag
           ORDER BY total DESC'''
    )
    rows = cur.fetchall()
    tags = []
    for r in rows:
        total = r['total'] or 0
        correct = r['correct'] or 0
        tags.append({
            'name': r['knowledge_tag'],
            'total': total,
            'correct': correct,
            'accuracy': correct / total if total else 0,
        })
    return {'tags': tags}


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
        'case_material': row['case_material'] or '',
    }


def regenerate_note_questions(db, note_id, questions):
    """删除 note_id 下原有的题目和作答记录，插入新的题目列表。"""
    cur = db.cursor()
    # 删除旧作答记录
    cur.execute('SELECT id FROM questions WHERE note_id = ?', (note_id,))
    q_ids = [row['id'] for row in cur.fetchall()]
    if q_ids:
        placeholders = ','.join('?' for _ in q_ids)
        cur.execute(f'DELETE FROM user_answers WHERE question_id IN ({placeholders})', tuple(q_ids))
    # 删除旧题目
    cur.execute('DELETE FROM questions WHERE note_id = ?', (note_id,))
    db.commit()
    # 插入新题目
    insert_question_batch(db, note_id, questions)
    # 返回新题目数量
    cur.execute('SELECT COUNT(*) FROM questions WHERE note_id = ?', (note_id,))
    return cur.fetchone()[0]


def update_question(db, question_id, **kwargs):
    """更新指定题目的字段。可更新: content, options, answer, analysis, knowledge_tag, difficulty, q_type。"""
    allowed = {'content', 'options', 'answer', 'analysis', 'knowledge_tag', 'difficulty', 'q_type', 'case_material'}
    updates = {}
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            updates[k] = v
    if not updates:
        return False
    # 序列化 options
    if 'options' in updates and isinstance(updates['options'], list):
        updates['options'] = json.dumps(updates['options'], ensure_ascii=False)
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values())
    values.append(question_id)
    cur = db.cursor()
    cur.execute(f'UPDATE questions SET {set_clause} WHERE id = ?', tuple(values))
    db.commit()
    return cur.rowcount > 0


def delete_question(db, question_id):
    """删除指定题目及其作答记录。"""
    cur = db.cursor()
    cur.execute('DELETE FROM user_answers WHERE question_id = ?', (question_id,))
    cur.execute('DELETE FROM questions WHERE id = ?', (question_id,))
    db.commit()
    return cur.rowcount > 0
