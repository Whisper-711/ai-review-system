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
    get_question_by_id,
    delete_note,
)
from coze_client import CozeClient


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
    coze_client = CozeClient(api_key, os.getenv('COZE_BOT_ID', ''))

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

    @app.route('/api/notes/upload', methods=['POST'])
    def upload_note():
        file = request.files.get('file')
        title = request.form.get('title', '')

        if not file:
            return jsonify({'error': 'no file'}), 400

        filename = file.filename
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        with open(save_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        db = get_db()
        note_id = insert_note(db, title or filename, save_path)

        # 读取出题配置：题型 & 目标题量
        question_types = request.form.getlist('question_types')
        if not question_types:
            question_types = ['single_choice', 'short_answer']
        max_questions_raw = request.form.get('max_questions', '').strip()
        max_questions = None
        if max_questions_raw.isdigit() and int(max_questions_raw) > 0:
            max_questions = int(max_questions_raw)

        # 让模型自己从笔记中总结知识点并生成题目
        questions = coze_client.generate_questions_from_note(
            content,
            '',
            question_types=question_types,
            max_questions=max_questions,
        )
        insert_question_batch(db, note_id, questions)

        return jsonify({'note_id': note_id, 'question_count': len(questions)})

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

    @app.route('/api/notes', methods=['GET'])
    def api_notes():
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT id, title, created_at FROM notes ORDER BY created_at DESC LIMIT 50')
        rows = cur.fetchall()
        notes = []
        for r in rows:
            notes.append({'id': r['id'], 'title': r['title'], 'created_at': r['created_at']})
        return jsonify({'notes': notes})

    @app.route('/api/notes/<int:note_id>/delete', methods=['POST'])
    def api_delete_note(note_id):
        db = get_db()
        delete_note(db, note_id)
        return jsonify({'status': 'ok'})

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

        if question.get('q_type') == 'short_answer':
            # 简答题走千问评分
            score_0_1, comment = coze_client.score_answer(question, user_answer or '')
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

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
