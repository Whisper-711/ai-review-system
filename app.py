import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv

from database import init_db, get_db, close_db
from models import (
    insert_note,
    insert_question_batch,
    get_questions_by_knowledge,
    insert_answer,
    get_wrong_questions,
    get_stats_overview,
    get_stats_by_tag,
    get_question_by_id,
    delete_note,
    update_question,
    delete_question,
    search_questions,
    regenerate_note_questions,
)
from dashscope_client import DashScopeClient


load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    init_db()

    # 确保每次请求结束后关闭数据库连接
    @app.teardown_appcontext
    def teardown_db(exception=None):
        close_db(exception)

    # 优先使用 DashScope/通义的环境变量名，兼容旧的 COZE_API_KEY
    api_key = os.getenv('DASHSCOPE_API_KEY') or os.getenv('COZE_API_KEY', '')
    dashscope_client = DashScopeClient(api_key, os.getenv('COZE_BOT_ID', ''))

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/practice')
    def practice_page():
        return render_template('practice.html')

    @app.route('/wrong')
    def wrong_page():
        return render_template('wrong.html')

    @app.route('/dashboard')
    def dashboard_page():
        return render_template('dashboard.html')

    @app.route('/exam')
    def exam_page():
        return render_template('exam.html')

    @app.route('/search')
    def search_page():
        return render_template('search.html')

    # 允许的文件扩展名
    ALLOWED_EXTENSIONS = {'.txt', '.md', '.markdown', '.py', '.js', '.ts', '.java', '.cpp', '.json', '.yaml', '.yml', '.html', '.css', '.xml'}

    @app.route('/api/notes/upload', methods=['POST'])
    def upload_note():
        files = request.files.getlist('file') if request.files.getlist('file')[0] else [request.files.get('file')]
        title = request.form.get('title', '')

        if not files or not files[0] or files[0].filename == '':
            return jsonify({'error': 'no file'}), 400

        # 读取出题配置：题型 & 目标题量
        question_types = request.form.getlist('question_types')
        if not question_types:
            question_types = ['single_choice', 'short_answer']
        max_questions_raw = request.form.get('max_questions', '').strip()
        max_questions = None
        if max_questions_raw.isdigit() and int(max_questions_raw) > 0:
            max_questions = min(int(max_questions_raw), 100)  # 上限 100 道

        results = []
        db = get_db()

        for file in files:
            if not file or file.filename == '':
                continue

            # 文件扩展名校验
            ext = os.path.splitext(file.filename)[1].lower()
            if ext and ext not in app.config.get('ALLOWED_EXTENSIONS', ALLOWED_EXTENSIONS):
                results.append({'filename': file.filename, 'error': f'不支持的文件类型: {ext}'})
                continue

            # 读取文件内容
            try:
                content = file.read().decode('utf-8')
            except UnicodeDecodeError:
                content = file.read().decode('gbk', errors='ignore')
            if not content.strip():
                results.append({'filename': file.filename, 'error': '文件内容为空'})
                continue

            save_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content)

            note_title = title or file.filename
            note_id = insert_note(db, note_title, save_path)

            # 让模型从笔记中生成题目
            questions = dashscope_client.generate_questions_from_note(
                content,
                '',
                question_types=question_types,
                max_questions=max_questions,
            )
            insert_question_batch(db, note_id, questions)
            results.append({
                'filename': file.filename,
                'note_id': note_id,
                'question_count': len(questions),
            })

        return jsonify({'results': results})

    @app.route('/api/questions/by_knowledge', methods=['GET'])
    def api_questions_by_knowledge():
        tags = request.args.get('knowledge_tags', '')
        limit = int(request.args.get('limit', 10))
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]

        note_id_raw = request.args.get('note_id')
        note_id = int(note_id_raw) if note_id_raw and note_id_raw.isdigit() else None
        scope = request.args.get('scope', '').strip() or None
        q_type = request.args.get('q_type', '').strip() or None

        db = get_db()
        questions = get_questions_by_knowledge(db, tag_list, limit, note_id=note_id, scope=scope, q_type=q_type)
        return jsonify({'questions': questions})

    @app.route('/api/knowledge_tags', methods=['GET'])
    def api_knowledge_tags():
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT DISTINCT knowledge_tag FROM questions WHERE knowledge_tag != "" ORDER BY knowledge_tag')
        tags = [row['knowledge_tag'] for row in cur.fetchall()]
        return jsonify({'tags': tags})

    @app.route('/api/notes', methods=['GET'])
    def api_notes():
        db = get_db()
        cur = db.cursor()
        cur.execute('''
            SELECT n.id, n.title, n.created_at, COUNT(q.id) AS question_count
            FROM notes n
            LEFT JOIN questions q ON q.note_id = n.id
            GROUP BY n.id
            ORDER BY n.created_at DESC
            LIMIT 50
        ''')
        rows = cur.fetchall()
        notes = []
        for r in rows:
            notes.append({
                'id': r['id'],
                'title': r['title'],
                'created_at': r['created_at'],
                'question_count': r['question_count'],
            })
        return jsonify({'notes': notes})

    @app.route('/api/notes/<int:note_id>/content', methods=['GET'])
    def api_note_content(note_id):
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT id, title, path FROM notes WHERE id = ?', (note_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': 'note not found'}), 404
        try:
            with open(row['path'], 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except FileNotFoundError:
            return jsonify({'error': 'file not found'}), 404
        return jsonify({
            'id': row['id'],
            'title': row['title'],
            'content': content[:5000],  # 预览前 5000 字
            'truncated': len(content) > 5000,
        })

    @app.route('/api/notes/<int:note_id>/delete', methods=['POST'])
    def api_delete_note(note_id):
        db = get_db()
        delete_note(db, note_id)
        return jsonify({'status': 'ok'})

    @app.route('/api/notes/<int:note_id>/questions', methods=['GET'])
    def api_note_questions(note_id):
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM questions WHERE note_id = ? ORDER BY id', (note_id,))
        rows = cur.fetchall()
        from models import _row_to_question_dict
        questions = [_row_to_question_dict(r) for r in rows]
        return jsonify({'questions': questions})

    @app.route('/api/export', methods=['GET'])
    def api_export():
        fmt = request.args.get('format', 'json')
        note_id_raw = request.args.get('note_id', '').strip()
        q_type = request.args.get('q_type', '').strip() or None

        db = get_db()
        sql = 'SELECT * FROM questions WHERE 1=1'
        params = []
        if note_id_raw and note_id_raw.isdigit():
            sql += ' AND note_id = ?'
            params.append(int(note_id_raw))
        if q_type:
            sql += ' AND q_type = ?'
            params.append(q_type)
        sql += ' ORDER BY id'
        cur = db.cursor()
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        from models import _row_to_question_dict
        questions = [_row_to_question_dict(r) for r in rows]

        if fmt == 'txt':
            lines = []
            for q in questions:
                type_map = {'single_choice': '单选', 'true_false': '判断', 'short_answer': '简答', 'case_analysis': '案例', 'fill_blank': '填空'}
                t = type_map.get(q['q_type'], q['q_type'])
                lines.append(f"[{t}] #{q['id']} ({q['knowledge_tag']})")
                lines.append(f"  题干: {q['content']}")
                if q.get('options'):
                    lines.append(f"  选项: {' | '.join(q['options'])}")
                lines.append(f"  答案: {q['answer']}")
                if q.get('analysis'):
                    lines.append(f"  解析: {q['analysis']}")
                lines.append('')
            text = '\n'.join(lines)
            return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

        elif fmt == 'md':
            lines = []
            for q in questions:
                type_map = {'single_choice': '单选', 'true_false': '判断', 'short_answer': '简答', 'case_analysis': '案例', 'fill_blank': '填空'}
                t = type_map.get(q['q_type'], q['q_type'])
                lines.append(f'## [{t}] {q["content"]}')
                lines.append(f'')
                lines.append(f'- **ID**: #{q["id"]}  ')
                lines.append(f'- **知识点**: {q["knowledge_tag"] or "未标注"}  ')
                lines.append(f'- **难度**: {q["difficulty"] or "未标注"}  ')
                if q.get('options'):
                    lines.append(f'- **选项**: {" | ".join(q["options"])}  ')
                lines.append(f'- **答案**: {q["answer"]}  ')
                if q.get('analysis'):
                    lines.append(f'- **解析**: {q["analysis"]}  ')
                lines.append(f'')
                lines.append(f'---')
                lines.append(f'')
            text = '\n'.join(lines)
            return text, 200, {'Content-Type': 'text/markdown; charset=utf-8'}

        return jsonify({'error': 'unsupported format'}), 400

    @app.route('/api/questions/<int:question_id>/edit', methods=['POST'])
    def api_edit_question(question_id):
        data = request.get_json(force=True)
        db = get_db()
        ok = update_question(db, question_id, **data)
        if not ok:
            return jsonify({'error': 'question not found or no changes'}), 404
        q = get_question_by_id(db, question_id)
        return jsonify({'status': 'ok', 'question': q})

    @app.route('/api/questions/<int:question_id>/delete', methods=['POST'])
    def api_delete_question(question_id):
        db = get_db()
        ok = delete_question(db, question_id)
        if not ok:
            return jsonify({'error': 'question not found'}), 404
        return jsonify({'status': 'ok'})

    @app.route('/api/questions/<int:question_id>', methods=['GET'])
    def api_get_question(question_id):
        db = get_db()
        q = get_question_by_id(db, question_id)
        if not q:
            return jsonify({'error': 'not found'}), 404
        return jsonify({'question': q})

    @app.route('/api/answers/submit', methods=['POST'])
    def api_submit_answer():
        data = request.get_json(force=True)
        question_id = data.get('question_id')
        user_answer = data.get('user_answer')

        if question_id is None:
            return jsonify({'error': 'question_id required'}), 400

        db = get_db()
        question = get_question_by_id(db, question_id)
        if not question:
            return jsonify({'error': 'question not found'}), 404

        score_0_1 = 0.0
        comment = ''
        sub_scores = {}

        if question.get('q_type') == 'case_analysis':
            # 案例分析题走 AI 评分（综合评分）
            score_0_1, comment, sub_scores = dashscope_client.score_case_answer(question, user_answer or '')
            is_correct = score_0_1 >= 0.5
        elif question.get('q_type') == 'fill_blank':
            # 填空题走 AI 评分
            score_0_1, comment = dashscope_client.score_fill_blank(question, user_answer or '')
            is_correct = score_0_1 >= 0.6
        elif question.get('q_type') == 'short_answer':
            # 简答题走千问评分
            score_0_1, comment = dashscope_client.score_answer(question, user_answer or '')
            is_correct = score_0_1 >= 0.6
        else:
            # 选择题对比：优先按选项字母（A/B/C/D）归一化比较，避免 "C" vs "C. xxx" 判错
            ua = str(user_answer or '').strip()
            sa = str(question.get('answer', '')).strip()

            def normalize_choice(s: str) -> str:
                s = s.strip()
                if not s:
                    return ''
                first = s[0].upper()
                # 支持 A~Z 作为选项前缀，方便扩展到 4 个以上选项
                if 'A' <= first <= 'Z':
                    return first
                return s

            ua_norm = normalize_choice(ua)
            sa_norm = normalize_choice(sa)
            is_correct = ua_norm == sa_norm

        insert_answer(db, question_id, user_answer, bool(is_correct))

        return jsonify(
            {
                'status': 'ok',
                'is_correct': bool(is_correct),
                'score': int(round(score_0_1 * 100)),  # 0~100 分
                'comment': comment,
                'sub_scores': sub_scores,
                'standard_answer': question.get('answer', ''),
                'analysis': question.get('analysis', ''),
                'q_type': question.get('q_type', ''),
            }
        )

    @app.route('/api/review/wrong', methods=['GET'])
    def api_review_wrong():
        limit = int(request.args.get('limit', 20))
        db = get_db()
        questions = get_wrong_questions(db, limit)
        return jsonify({'questions': questions})

    @app.route('/api/stats/overview', methods=['GET'])
    def api_stats_overview():
        db = get_db()
        stats = get_stats_overview(db)
        return jsonify(stats)

    @app.route('/api/stats/by_tag', methods=['GET'])
    def api_stats_by_tag():
        db = get_db()
        stats = get_stats_by_tag(db)
        return jsonify(stats)

    @app.route('/api/questions/search', methods=['GET'])
    def api_search_questions():
        q = request.args.get('q', '')
        q_type = request.args.get('q_type', '')
        difficulty = request.args.get('difficulty', '')
        knowledge_tag = request.args.get('knowledge_tag', '')
        note_id_raw = request.args.get('note_id', '')
        note_id = int(note_id_raw) if note_id_raw.isdigit() else None
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        db = get_db()
        result = search_questions(db, q=q, q_type=q_type, difficulty=difficulty,
                                  knowledge_tag=knowledge_tag, note_id=note_id,
                                  page=page, per_page=per_page)
        return jsonify(result)

    @app.route('/api/questions/<int:question_id>/chat', methods=['POST'])
    def api_question_chat(question_id):
        """AI 追问 — 针对某道题进行深度讲解。"""
        data = request.get_json(force=True)
        user_message = data.get('user_message', '')
        if not user_message.strip():
            return jsonify({'error': '请输入您的问题'}), 400

        db = get_db()
        q = get_question_by_id(db, question_id)
        if not q:
            return jsonify({'error': 'question not found'}), 404

        # 从请求中获取用户作答和历史
        user_answer = data.get('user_answer', '')
        chat_history = data.get('chat_history', [])

        reply = dashscope_client.follow_up_chat(q, user_answer, chat_history, user_message)
        return jsonify({'reply': reply})

    @app.route('/api/exam/start', methods=['GET'])
    def api_exam_start():
        """开始考试 — 按配置随机抽题，返回不含答案的题目列表。"""
        question_count = int(request.args.get('question_count', 10))
        q_type = request.args.get('q_type', '')
        difficulty = request.args.get('difficulty', '')
        note_id_raw = request.args.get('note_id', '')
        note_id = int(note_id_raw) if note_id_raw.isdigit() else None

        db = get_db()
        # 构建过滤条件
        tag_list = []
        questions = get_questions_by_knowledge(
            db, tag_list, limit=question_count,
            note_id=note_id, q_type=q_type or None)

        # 按难度过滤（如果有）
        if difficulty:
            cur = db.cursor()
            cur.execute('SELECT * FROM questions WHERE difficulty = ? ORDER BY RANDOM() LIMIT ?',
                        (difficulty, question_count))
            rows = cur.fetchall()
            from models import _row_to_question_dict
            questions = [_row_to_question_dict(r) for r in rows]

        # 不返回答案/解析，放到后面提交时再给
        exam_questions = []
        for q in questions:
            exam_questions.append({
                'id': q['id'],
                'q_type': q['q_type'],
                'content': q['content'],
                'options': q['options'],
                'knowledge_tag': q['knowledge_tag'],
                'difficulty': q['difficulty'],
                'case_material': q.get('case_material', ''),
            })

        return jsonify({
            'questions': exam_questions,
            'total': len(exam_questions),
        })

    @app.route('/api/exam/submit', methods=['POST'])
    def api_exam_submit():
        """提交考试 — 批量评分并返回成绩报告。"""
        data = request.get_json(force=True)
        answers = data.get('answers', [])
        if not answers:
            return jsonify({'error': 'no answers'}), 400

        db = get_db()
        results = []
        correct_count = 0
        for item in answers:
            qid = item.get('question_id')
            ua = item.get('user_answer', '')
            q = get_question_by_id(db, qid)
            if not q:
                continue

            is_correct = False
            score_0_1 = 0.0
            comment = ''

            if q['q_type'] == 'single_choice' or q['q_type'] == 'true_false':
                ua_norm = ua.strip()[0].upper() if ua.strip() else ''
                sa_norm = (q['answer'] or '').strip()[0].upper() if q.get('answer', '') else ''
                is_correct = ua_norm == sa_norm and bool(ua_norm)
                score_0_1 = 1.0 if is_correct else 0.0
            elif q['q_type'] == 'short_answer':
                score_0_1, comment = dashscope_client.score_answer(q, ua)
                is_correct = score_0_1 >= 0.6
            elif q['q_type'] == 'fill_blank':
                score_0_1, comment = dashscope_client.score_fill_blank(q, ua)
                is_correct = score_0_1 >= 0.6
            elif q['q_type'] == 'case_analysis':
                score_0_1, comment, _ = dashscope_client.score_case_answer(q, ua)
                is_correct = score_0_1 >= 0.5

            insert_answer(db, qid, ua, bool(is_correct))
            if is_correct:
                correct_count += 1

            results.append({
                'question_id': qid,
                'q_type': q['q_type'],
                'knowledge_tag': q['knowledge_tag'],
                'content': q['content'],
                'user_answer': ua,
                'is_correct': bool(is_correct),
                'score': int(round(score_0_1 * 100)),
                'comment': comment,
                'standard_answer': q.get('answer', ''),
                'analysis': q.get('analysis', ''),
            })

        total = len(results)
        # 按知识点聚合
        from collections import Counter
        tag_correct = Counter()
        tag_total = Counter()
        for r in results:
            tag = r.get('knowledge_tag', '未知') or '未知'
            tag_total[tag] += 1
            if r['is_correct']:
                tag_correct[tag] += 1
        by_tag = [{'name': t, 'total': tag_total[t], 'correct': tag_correct[t],
                   'accuracy': tag_correct[t] / tag_total[t] if tag_total[t] else 0}
                  for t in tag_total]

        return jsonify({
            'total': total,
            'correct_count': correct_count,
            'score': int(round(correct_count / total * 100)) if total else 0,
            'by_tag': by_tag,
            'results': results,
        })

    @app.route('/api/notes/<int:note_id>/regenerate', methods=['POST'])
    def api_regenerate_questions(note_id):
        """重新生成指定笔记模块的题目。"""
        data = request.get_json(force=True) or {}
        question_types = data.get('question_types', ['single_choice', 'short_answer'])
        max_questions_raw = data.get('max_questions', '')
        max_questions = None
        if isinstance(max_questions_raw, (int, str)):
            s = str(max_questions_raw).strip()
            if s.isdigit() and int(s) > 0:
                max_questions = min(int(s), 100)

        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT id, title, path FROM notes WHERE id = ?', (note_id,))
        note = cur.fetchone()
        if not note:
            return jsonify({'error': 'note not found'}), 404

        try:
            with open(note['path'], 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except FileNotFoundError:
            return jsonify({'error': 'note file not found'}), 404

        if not content.strip():
            return jsonify({'error': 'note content is empty'}), 400

        questions = dashscope_client.generate_questions_from_note(
            content, '', question_types=question_types, max_questions=max_questions)
        if not questions:
            return jsonify({'error': 'AI 生成题目失败，请稍后重试'}), 500

        new_count = regenerate_note_questions(db, note_id, questions)
        return jsonify({'status': 'ok', 'question_count': new_count})

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
