import json
import requests


class CozeClient:
    """兼容原有名称的客户端，实现为调用阿里云 DashScope 千问模型。

    说明：
    - api_key: 使用阿里云 DashScope 控制台获取的 API Key。
    - bot_id: 为兼容旧代码保留的参数，这里不会使用。
    """

    def __init__(self, api_key: str, bot_id: str):
        self.api_key = api_key
        # bot_id 暂不使用，仅为兼容
        self.base_url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
        # 这里可以根据你在 DashScope 控制台选择的具体模型调整
        self.model = 'qwen-turbo'

    def generate_questions_from_note(self, note_text: str, knowledge_tags: str = '', question_types=None, max_questions=None):
        """调用千问，根据笔记文本生成结构化题目列表。

        返回格式：
        [
          {
            'knowledge_tag': str,
            'q_type': 'single_choice' 或 'short_answer',
            'content': str,
            'options': [str, ...],
            'answer': str,
            'analysis': str,
            'difficulty': str,
          },
          ...
        ]
        """

        if not self.api_key:
            return []

        # 默认题型：单选 + 简答
        if not question_types:
            question_types = ['single_choice', 'short_answer']

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        # 构造提示词，请求模型以 JSON 格式返回题目
        prompt_parts = [
            '你是一个 AI 方向面试题生成助手。',
            '请根据以下学习笔记内容，为我生成若干道 AI / 深度学习 / 大模型 相关的面试题。',
        ]

        # 题型约束描述
        type_desc_map = {
            'single_choice': '单选题 (single_choice)',
            'short_answer': '简答题 (short_answer)',
        }
        type_desc = '、'.join(type_desc_map.get(t, t) for t in question_types)
        prompt_parts.append(f'题目类型仅包括：{type_desc}。')

        # 数量约束
        if isinstance(max_questions, int) and max_questions > 0:
            prompt_parts.append(f'总题目数量不超过 {max_questions} 道。请覆盖尽可能多的重要知识点。')
        else:
            prompt_parts.append('题目数量可根据笔记长度与知识点多少自行决定，但请覆盖尽可能多的重要知识点。')

        prompt_parts.append(
            '请你自行从内容中提炼每道题对应的“主要知识点”，用非常简短的中文短语填写到 knowledge_tag 字段中，例如:"神经网络基础"、"反向传播"、"Transformer 结构" 等。'
        )

        # 对单选题的选项和答案做更严格约束，避免出现「没有正确答案」的情况
        prompt_parts.append(
            '对于 single_choice 单选题：\n'
            '1. 请生成 4~6 个选项，放在 options 数组中。\n'
            '2. 每个选项必须以前缀 "A. ", "B. ", "C. " 等大写英文字母加点加空格开头，例如 "A. 选项内容"。\n'
            '3. 答案 answer 字段只填写正确选项的字母，例如 "A"、"B"、"C"，不要带句号和内容。\n'
            '4. 必须且只能有一个正确选项，不能出现所有选项都不正确或有多个都正确的情况。'
        )

        prompt_parts.append(
            '请直接输出 JSON，格式为：\n'
            '[\n'
            '  {"knowledge_tag": "知识点", "q_type": "single_choice", "content": "题干",'
            '   "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"], "answer": "C",'
            '   "analysis": "解析", "difficulty": "easy/medium/hard"},\n'
            '  {"knowledge_tag": "知识点", "q_type": "short_answer", "content": "题干",'
            '   "options": [], "answer": "参考答案", "analysis": "解析", "difficulty": "medium"}\n'
            ']\n'
            '不要输出任何解释或多余文字，只输出 JSON。'
        )

        prompt_parts.append('以下是学习笔记内容：')
        prompt_parts.append(note_text[:8000])  # 避免一次性内容过长
        prompt = '\n\n'.join(prompt_parts)

        # 按 DashScope 文档，使用 messages 对话形式
        payload = {
            'model': self.model,
            'input': {
                'messages': [
                    {
                        'role': 'user',
                        'content': prompt,
                    }
                ]
            },
        }

        try:
            resp = requests.post(self.base_url, headers=headers, data=json.dumps(payload), timeout=120)
            # 如果是 4xx/5xx，让 raise_for_status 抛异常被下面捕获
            resp.raise_for_status()
            data = resp.json()

            # DashScope 文本生成典型返回：data['output']['text'] 或 data['output']['choices'][0]['text'] 等
            # 这里做兼容处理，你可以根据实际返回结构适当调整。
            output_text = None
            if isinstance(data.get('output'), dict):
                if isinstance(data['output'].get('choices'), list) and data['output']['choices']:
                    output_text = data['output']['choices'][0].get('text')
                elif 'text' in data['output']:
                    output_text = data['output'].get('text')

            if not output_text:
                # 兜底：如果结构不同，直接从 data 里找第一个字符串
                output_text = self._extract_first_str(data)

            if not output_text:
                # 打印一下完整响应，方便调试
                print('DashScope response without obvious text field:', data)
                return []

            # 去掉可能的前后空白，尝试解析为 JSON
            output_text = output_text.strip()

            # 有些时候模型会在 JSON 前后加 ```json 这样的标记，做一次清洗
            if output_text.startswith('```'):
                output_text = output_text.strip('`')
                output_text = output_text.replace('json', '', 1).strip()

            questions_raw = json.loads(output_text)
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
                    }
                )
            return parsed
        except Exception as e:
            # 打印状态码和返回内容，方便在本地终端看到问题
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
            for v in obj.values():
                s = CozeClient._extract_first_str(v)
                if s:
                    return s
        if isinstance(obj, list):
            for v in obj:
                s = CozeClient._extract_first_str(v)
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

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        prompt = (
            '你是一个严谨的 AI 面试题阅卷老师，请根据下面的信息对考生的简答题作答进行评分与点评。\n'
            '请返回 JSON 格式：{"score": 0-1 的小数, "comment": "简短中文点评"}，不要输出其他内容。\n\n'
            f'【题干】{question.get("content", "")}\n'
            f'【知识点】{question.get("knowledge_tag", "")}\n'
            f'【参考答案】{question.get("answer", "")}\n'
            f'【考生作答】{user_answer}\n'
        )

        payload = {
            'model': self.model,
            'input': {
                'messages': [
                    {
                        'role': 'user',
                        'content': prompt,
                    }
                ]
            },
        }

        try:
            resp = requests.post(self.base_url, headers=headers, data=json.dumps(payload), timeout=120)
            resp.raise_for_status()
            data = resp.json()

            output_text = None
            if isinstance(data.get('output'), dict):
                if isinstance(data['output'].get('choices'), list) and data['output']['choices']:
                    output_text = data['output']['choices'][0].get('text')
                elif 'text' in data['output']:
                    output_text = data['output'].get('text')

            if not output_text:
                output_text = self._extract_first_str(data)
            if not output_text:
                return 0.0, '评分失败，模型未返回内容。'

            output_text = output_text.strip()
            if output_text.startswith('```'):
                output_text = output_text.strip('`')
                output_text = output_text.replace('json', '', 1).strip()

            js = json.loads(output_text)
            score = float(js.get('score', 0))
            comment = str(js.get('comment', '')) or '无详细点评。'
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
