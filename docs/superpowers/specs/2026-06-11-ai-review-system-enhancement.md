# AI 复习问答系统 — 功能扩展设计 Spec

## 概述

在现有 AI 复习问答系统基础上增加 7 项功能：AI 追问讲解、知识点掌握度分析、考试模式、重新生成题目、全文搜索与高级筛选、案例分析题、答题布局优化。

## 1. 案例分析题 (Case Analysis)

### 数据模型

在 `questions` 表新增字段：
- `case_material TEXT` — 案例材料文本（题干是简短的引导问题）

案例分析题 `q_type = 'case_analysis'`，由 AI 根据笔记内容自动生成。

### API

- `POST /api/notes/upload` — 已有接口，当 `question_types` 包含 `case_analysis` 时，AI 生成含 `case_material` 的题目
- `POST /api/answers/submit` — 已有接口，案例分析题走 AI 评分（类似简答题），AI 综合考核：是否结合案例、逻辑是否清晰、覆盖是否全面

### DashScope 客户端

- `generate_questions_from_note` — 扩展支持 `case_analysis` 题型，prompt 要求模型输出 `case_material` 字段（500~1500 字案例 + 1~3 个子问题）
- `score_case_answer` — 评分方法，返回 `{score: 0~1, comment, sub_scores: [...]}`

### 前端

- 答题时先展示案例材料（醒目区块），再展示子问题
- 每个子问题独立 textarea
- 提交后展示 AI 综合评分 + 子项评分

## 2. AI 追问讲解 (Follow-up Chat)

### API

- `POST /api/questions/<id>/chat`
  - 请求体：`{user_message, context: {question, user_answer, result}}`
  - 响应：`{reply: "..."}`
- 调用 DashScope，将题目信息 + 用户追问一起发给模型，返回讲解内容

### 前端

- 提交答案并展示反馈后，在反馈区下方显示追问输入框
- 追问后回复以聊天气泡追加在反馈区
- 支持连续追问

## 3. 知识点掌握度分析

### API

- `GET /api/stats/by_tag`
  - 响应：`{tags: [{name, total, correct, accuracy}, ...]}`

### 后端

- 从 `questions` 和 `user_answers` 按 `knowledge_tag` 聚合统计

### 前端 (Dashboard)

- 新增 ECharts 雷达图（radar chart），展示各知识点掌握度
- 低于 40% 的知识点高亮标红，并显示"建议重点复习"提示

## 4. 考试模式

### 新页面 `/exam`

### API

- `GET /api/exam/start?question_count=20&minutes=30&q_type=&difficulty=&note_id=`
  - 返回题目列表（不包含答案），总时限
- `POST /api/exam/submit`
  - 请求体：`{answers: [{question_id, user_answer}, ...]}`
  - 响应：`{score, correct_count, total_count, by_tag: [...], results: [...]}`

### 后端

- 抽题逻辑类似 `/api/questions/by_knowledge`，按配置随机抽取
- 返回时不返回 `answer` 和 `analysis`
- 提交时批量评分，选择题直接比对，简答/案例调用 AI 评分
- 考试服务端计时的简易实现：前端倒计时 + 提交时校验时间

### 前端

- 考试配置面板（题量、时长、题型、难度、模块）
- 开始考试后全屏答题模式
- 右上角倒计时，超时自动提交
- 左侧题号导航（已答/未答/当前高亮）
- 提交后展示成绩报告：总分、每题结果、知识点分析

## 5. 重新生成题目

### API

- `POST /api/notes/<id>/regenerate`
  - 请求体：`{question_types, max_questions}`
  - 响应：`{question_count, questions: [...]}`
- 逻辑：用笔记原文重新调用 AI 生成题目，替换该 note_id 下的所有题目

### 前端

- 模块管理弹窗中增加「重新生成」按钮
- 点击后弹出配置选项（题型、题量），确认后调用 API
- 生成过程中显示 loading 状态

## 6. 全文搜索 + 高级筛选

### API

- `GET /api/questions/search?q=&q_type=&difficulty=&knowledge_tag=&note_id=&page=&per_page=`
  - `q` 搜索题干、答案、解析、案例材料
  - `q_type` / `difficulty` / `knowledge_tag` / `note_id` 过滤
  - 分页支持
  - 响应：`{questions, total, page, per_page}`

### 后端

- SQL 用 `LIKE %keyword%` 在 `content`, `answer`, `analysis`, `case_material` 中搜索
- 组合过滤条件

### 前端

- 新增 `/search` 页面，或集成到现有页面
- 搜索框（带搜索图标）+ 筛选项下拉
- 结果列表展示，每条可快速跳转到练习

## 7. 答题布局优化

### 练习页面 (`/practice`)

- 增大聊天区高度 460px → 580px
- 字体增大 text-xs → text-sm (14px)
- 选项区域 padding 加大，radio 点击区域更宽松
- 当前题目区移到左侧与聊天区合并，右侧留空或放追问区
- 整体间距加大，减少视觉拥挤

### 错题页面 (`/wrong`)

- 错题列表字体增大
- 错题练习区布局优化

### Dashboard

- 雷达图居中，数据卡片增加边距

## 数据库变更

```sql
ALTER TABLE questions ADD COLUMN case_material TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_questions_q_type ON questions(q_type);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
```

## 实现顺序

1. 数据库变更 + `models.py` 扩展
2. `dashscope_client.py` 扩展（案例题生成 + 评分 + 追问）
3. `app.py` 新增路由
4. 全文搜索 + 高级筛选（前端）
5. 案例分析题（前端）
6. AI 追问（前端）
7. 知识点掌握度雷达图
8. 重新生成题目按钮
9. 考试模式（完整新页面）
10. 答题布局优化（收尾）

## 技术要点

- 所有 UI 继续使用 Tailwind CSS
- ECharts 已引入 Dashboard，雷达图直接用
- AI 追问使用流式 SSE 或普通 POST，考虑到简化先 POST
- 考试模式前端倒计时使用 `setInterval`，精确到秒
- SQLite 搜索用 `LIKE` 即可，不需要全文索引引擎
