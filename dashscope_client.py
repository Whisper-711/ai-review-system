import json
import requests


class DashScopeClient:
    """通义千问 / DashScope 的简单客户端封装。

    使用兼容模式端点 (OpenAI-compatible) 以支持 qwen3 系列模型。

    - api_key: 使用阿里云 DashScope 控制台获取的 API Key。
    - bot_id: 兼容保留参数，这里不会使用。
    """

    def __init__(self, api_key: str, bot_id: str = ''):
        self.api_key = api_key
        # bot_id 暂不使用，仅为兼容
        self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
        # qwen3.6-flash 模型
        self.model = 'qwen3.6-flash-2026-04-16'

    def _call(self, messages, timeout=120):
        """统一的 DashScope 兼容模式 API 调用。"""
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self.model,
            'messages': messages,
        }
        resp = requests.post(self.base_url, headers=headers, data=json.dumps(payload), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # 兼容模式返回格式：data['choices'][0]['message']['content']
        if isinstance(data.get('choices'), list) and len(data['choices']) > 0:
            return data['choices'][0]['message']['content']
        # 兜底：尝试从嵌套结构中提取第一个字符串
        fallback = self._extract_first_str(data)
        if fallback:
            return fallback
        print('DashScope response without expected format:', data)
        return ''

    def _call_with_json(self, messages, timeout=120):
        """调用 API 并解析返回的 JSON 内容。"""
        text = self._call(messages, timeout=timeout)
        if not text:
            return None
        text = text.strip()
        # 处理 markdown 代码块包裹
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('json'):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print('Failed to parse JSON from model response:', text[:200])
            return None

    def generate_questions_from_note(self, note_text: str, knowledge_tags: str = '', question_types=None, max_questions=None):
        """调用千问，根据笔记文本生成结构化题目列表。

        返回格式：
        [
          {
            'knowledge_tag': str,
            'q_type': 'single_choice' | 'short_answer' | 'true_false' | 'case_analysis',
            'content': str,
            'options': [str, ...],
            'answer': str,
            'analysis': str,
            'difficulty': str,
            'case_material': str (仅 case_analysis),
          },
          ...
        ]
        """

        if not self.api_key:
            return []

        # 默认题型：单选 + 简答
        if not question_types:
            question_types = ['single_choice', 'short_answer']

        # 构造提示词，请求模型以 JSON 格式返回题目
        prompt_parts = [
            '你是一个 AI 方向面试题生成助手。',
            '请根据以下学习笔记内容，为我生成若干道 AI / 深度学习 / 大模型 相关的面试题。',
        ]

        # 题型约束描述
        type_desc_map = {
            'single_choice': '单选题 (single_choice)',
            'short_answer': '简答题 (short_answer)',
            'true_false': '判断题 (true_false)',
            'case_analysis': '案例分析题 (case_analysis)',
        }
        type_desc = '、'.join(type_desc_map.get(t, t) for t in question_types)
        prompt_parts.append(f'题目类型仅包括：{type_desc}。')

        # 数量约束
        if isinstance(max_questions, int) and max_questions > 0:
            prompt_parts.append(f'请尽量生成接近 {max_questions} 道题（不超过此数）。覆盖尽量多的重要知识点，宁多勿少。')
        else:
            prompt_parts.append('请根据笔记内容充分挖掘知识点，尽可能多地生成题目，覆盖尽可能多的重要知识点。')

        prompt_parts.append(
            '请你自行从内容中提炼每道题对应的"主要知识点"，用非常简短的中文短语填写到 knowledge_tag 字段中，例如:"神经网络基础"、"反向传播"、"Transformer 结构" 等。'
        )

        # 对单选题的选项和答案做更严格约束
        prompt_parts.append(
            '对于 single_choice 单选题：\n'
            '1. 请生成 4~6 个选项，放在 options 数组中。\n'
            '2. 每个选项必须以前缀 "A. ", "B. ", "C. " 等大写英文字母加点加空格开头，例如 "A. 选项内容"。\n'
            '3. 答案 answer 字段只填写正确选项的字母，例如 "A"、"B"、"C"，不要带句号和内容。\n'
            '4. 必须且只能有一个正确选项，不能出现所有选项都不正确或有多个都正确的情况。\n'
            '对于 true_false 判断题：\n'
            '1. options 固定为 ["A. 对", "B. 错"]。\n'
            '2. answer 字段填写 "A"（对）或 "B"（错）。'
        )

        # 案例分析题约束
        if 'case_analysis' in question_types:
            prompt_parts.append(
                '对于 case_analysis 案例分析题：\n'
                '1. 每个案例分析题包含一段案例材料（case_material 字段），长度 300~800 字，内容为真实或贴近实际的场景描述。\n'
                '2. content 字段写引导性问题或总问题，例如"请分析以上案例中的技术选型优劣"。\n'
                '3. options 字段为空数组。\n'
                '4. answer 字段写详细的参考答案，包含关键得分点。\n'
                '5. analysis 字段写解析，说明从案例中哪些信息推导出答案。'
            )

        prompt_parts.append(
            '请直接输出 JSON，格式为：\n'
            '[\n'
            '  {"knowledge_tag": "知识点", "q_type": "single_choice", "content": "题干",'
            '   "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"], "answer": "C",'
            '   "analysis": "解析", "difficulty": "easy/medium/hard"},\n'
            '  {"knowledge_tag": "知识点", "q_type": "true_false", "content": "判断题干",'
            '   "options": ["A. 对", "B. 错"], "answer": "A",'
            '   "analysis": "解析", "difficulty": "easy"},\n'
            '  {"knowledge_tag": "知识点", "q_type": "short_answer", "content": "题干",'
            '   "options": [], "answer": "参考答案", "analysis": "解析", "difficulty": "medium"},\n'
            '  {"knowledge_tag": "知识点", "q_type": "case_analysis", "content": "题干",'
            '   "options": [], "case_material": "案例材料文本...", "answer": "参考答案", "analysis": "解析", "difficulty": "hard"}\n'
            ']\n'
            '不要输出任何解释或多余文字，只输出 JSON。'
        )

        prompt_parts.append('以下是学习笔记内容：')
        prompt_parts.append(note_text[:32000])  # 避免一次性内容过长
        prompt = '\n\n'.join(prompt_parts)

        messages = [
            {'role': 'user', 'content': prompt},
        ]

        try:
            questions_raw = self._call_with_json(messages)
            if not isinstance(questions_raw, list):
                return []

            parsed = []
            for q in questions_raw:
                if not isinstance(q, dict):
                    continue
                parsed.append(
                    {
                        'knowledge_tag': q.get('knowledge_tag', ''),
                        'q_type': q.get('q_type', ''),
                        'content': q.get('content', ''),
                        'options': q.get('options', []) or [],
                        'answer': q.get('answer', ''),
                        'analysis': q.get('analysis', ''),
                        'difficulty': q.get('difficulty', ''),
                        'case_material': q.get('case_material', ''),
                    }
                )
            return parsed
        except Exception as e:
            try:
                print('Error calling DashScope:', getattr(e, 'response', None) and getattr(e.response, 'status_code', None))
                print('Response text:', getattr(e, 'response', None) and getattr(e.response, 'text', None))
            except Exception:
                pass
            print('Error calling DashScope or parsing questions:', e)
            return []

    @staticmethod
    def _extract_first_str(obj):
        """从嵌套结构中找出第一个字符串，作为兜底输出。"""

        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            # 优先提取 content 字段
            if 'content' in obj and isinstance(obj['content'], str) and obj['content'].strip():
                return obj['content']
            for v in obj.values():
                s = DashScopeClient._extract_first_str(v)
                if s:
                    return s
        if isinstance(obj, list):
            for v in obj:
                s = DashScopeClient._extract_first_str(v)
                if s:
                    return s
        return None

    def score_answer(self, question: dict, user_answer: str):
        """使用千问对简答题进行评分与点评。

        返回 (score_0_1, comment_str)，其中 score_0_1 在 0~1 之间。
        如果调用失败，返回 (0.0, '评分失败，暂时按错误处理。')
        """

        if not self.api_key:
            return 0.0, '未配置 DashScope API Key，无法进行评分。'

        prompt = (
            '你是一个严谨的 AI 面试题阅卷老师，请根据下面的信息对考生的简答题作答进行评分与点评。\n'
            '请返回 JSON 格式：{"score": 0-1 的小数, "comment": "简短中文点评"}，不要输出其他内容。\n\n'
            f'【题干】{question.get("content", "")}\n'
            f'【知识点】{question.get("knowledge_tag", "")}\n'
            f'【参考答案】{question.get("answer", "")}\n'
            f'【考生作答】{user_answer}\n'
        )

        messages = [
            {'role': 'user', 'content': prompt},
        ]

        try:
            result = self._call_with_json(messages)
            if not isinstance(result, dict):
                return 0.0, '评分失败，模型返回格式异常。'

            score = float(result.get('score', 0))
            comment = str(result.get('comment', '')) or '无详细点评。'
            # 归一化到 0~1 范围
            if score > 1:
                score = score / 100.0
            score = max(0.0, min(1.0, score))
            return score, comment
        except Exception as e:
            try:
                print('Error calling DashScope for scoring:', getattr(e, 'response', None) and getattr(e.response, 'status_code', None))
                print('Score response text:', getattr(e, 'response', None) and getattr(e.response, 'text', None))
            except Exception:
                pass
            return 0.0, '评分失败，暂时按错误处理。'

    def score_case_answer(self, question: dict, user_answer: str):
        """对案例分析题进行 AI 评分，综合考虑要点覆盖、案例分析深度、逻辑性。

        返回 (score_0_1, comment_str, sub_scores)。
        """

        if not self.api_key:
            return 0.0, '未配置 API Key', {}

        prompt = (
            '你是一个严谨的 AI 面试阅卷老师，请对考生的案例分析题作答进行评分。\n'
            '请返回 JSON 格式：\n'
            '{\n'
            '  "score": 0-1 的小数（综合评分）,\n'
            '  "comment": "简短中文点评",\n'
            '  "sub_scores": {\n'
            '    "coverage": 0-1（要点覆盖是否全面）,\n'
            '    "depth": 0-1（分析深度，是否结合案例细节）,\n'
            '    "logic": 0-1（逻辑推理是否清晰合理）\n'
            '  }\n'
            '}\n'
            '不要输出其他内容。\n\n'
            f'【案例材料】{question.get("case_material", "")}\n'
            f'【问题】{question.get("content", "")}\n'
            f'【知识点】{question.get("knowledge_tag", "")}\n'
            f'【参考答案要点】{question.get("answer", "")}\n'
            f'【考生作答】{user_answer}\n'
        )

        messages = [
            {'role': 'user', 'content': prompt},
        ]

        try:
            result = self._call_with_json(messages)
            if not isinstance(result, dict):
                return 0.0, '评分失败', {}

            score = float(result.get('score', 0))
            comment = str(result.get('comment', '')) or '无详细点评。'
            if score > 1:
                score = score / 100.0
            score = max(0.0, min(1.0, score))

            sub = result.get('sub_scores', {}) or {}
            sub_scores = {
                'coverage': min(1.0, max(0.0, float(sub.get('coverage', 0)))),
                'depth': min(1.0, max(0.0, float(sub.get('depth', 0)))),
                'logic': min(1.0, max(0.0, float(sub.get('logic', 0)))),
            }
            return score, comment, sub_scores
        except Exception as e:
            print('Error scoring case answer:', e)
            return 0.0, '评分失败', {}

    def follow_up_chat(self, question: dict, user_answer: str, chat_history: list, user_message: str):
        """AI 追问 — 对当前题目进行深度讲解、举例或对比。

        参数：
        - question: 题目信息字典
        - user_answer: 用户对该题的作答
        - chat_history: 之前的追问历史 [{"role": "user"/"assistant", "content": "..."}]
        - user_message: 用户最新的追问

        返回：AI 回复字符串。
        """

        if not self.api_key:
            return '未配置 API Key，无法进行追问。'

        system_prompt = (
            '你是一个 AI 学习辅导老师。用户刚做了一道题，现在针对这道题向你追问。'
            '请根据题目信息、用户的作答情况，给出深入浅出的讲解、举例、对比或扩展知识。'
            '回答要详细但不啰嗦，结合题目上下文来讲解。'
        )

        context_parts = [
            f'【题目】{question.get("content", "")}',
        ]
        if question.get('options'):
            context_parts.append(f'【选项】{" | ".join(question["options"])}')
        context_parts.append(f'【标准答案】{question.get("answer", "")}')
        if question.get('analysis'):
            context_parts.append(f'【解析】{question.get("analysis", "")}')
        context_parts.append(f'【你的作答】{user_answer}')
        context_str = '\n'.join(context_parts)

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'以下是我刚做的一道题的信息：\n{context_str}\n\n我的问题是：{user_message}'},
        ]

        # 追加历史（最多保留最近 6 轮）
        for msg in chat_history[-6:]:
            messages.append(msg)

        try:
            text = self._call(messages)
            return text or '抱歉，暂时无法回答。'
        except Exception as e:
            print('Error in follow_up_chat:', e)
            return '抱歉，追问服务暂时不可用。'
