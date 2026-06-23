# Demo 帖 — GitHub Trending Daily（AI 驱动多维评价版）

> TRAE AI 创造力大赛初赛 Demo 帖

---

## 1. Demo 简介

### 是什么
**GitHub Trending Daily** 是一个 AI 驱动的 GitHub 热门项目分析平台，每日自动抓取全球 Trending 项目，通过**7 维健康度评分 + DeepSeek 大模型分析**生成三份智能日报，让你在浏览器里一站式发现真正有价值的开源项目。

### 核心亮点

| 功能 | 说明 |
|------|------|
| 📊 **基础日报（6板块）** | 🧨爆发 / 🏆质量标杆 / 🌱潜力新星 / ⚠️热度陷阱 / 🤖AI雷达 / 📊数据看板 |
| 🔧 **自定义日报** | 输入任意话题 → 自动生成专属日报（32话题模板 + 多厂商LLM动态解析）。AI话题自动调用垂类评分引擎 |
| 📧 **邮件推送** | 每日自动推送日报到邮箱，支持基础/自定义类型切换 |
| 🎨 **Web 交互** | 深色主题、TAB 切换、秒开响应、响应式布局 |

### 面向谁
- 关注技术趋势的**开发者**和技术管理者
- 追踪 AI/ML 开源动态的从业者
- 希望发现优质项目而非只看星数的技术爱好者

---

## 2. Demo 创作思路

### 痛点
每天刷 GitHub Trending，发现一个致命问题：**星数高的项目不一定是好项目**。有些项目 Star 暴涨但 issue 堆积如山、长期未更新、甚至权重不开源——传统的 Trending 列表只让你看到"热度"，看不到"健康度"。

### 解决的三个局限
1. **评分公式太简陋** — 只看星星，忽略了代码质量、社区活跃度、维护状态、工程成熟度
2. **推荐结果同质化** — 所有项目按同一个标准排，没有分类视角（我关心 AI，你关心游戏引擎，应该各看各的）
3. **缺少危险信号** — 用户不知道哪些项目是"热度陷阱"，哪些是真正的"质量标杆"

### 为什么做这个方向
- **真实刚需**：我自己每天看 Trending，深受现有排行局限
- **数据富矿未被利用**：GitHub REST API 免费提供了 issues/PR/contributors/releases/commits 等 7 个维度的数据，市面上没人整合
- **AI 加持差异化**：DeepSeek 自动为每个项目生成中文分析，这是市面上所有 Trending 工具都没有的

---

## 3. Demo 体验地址

### 方式一：本地运行

```bash
# 1. 克隆项目
cd GitHub_Trending_Projects_Summary
pip install -r requirements.txt

# 2. 配置 Token（可选，不配也能跑）
cp .env.example .env
# 编辑 .env，填入 GITHUB_TOKEN

# 3. 抓取数据 + 生成日报
python -B src/main.py

# 4. 启动 Web 服务
python -B src/main.py --web
# 浏览器打开 http://127.0.0.1:5000
```

> 首次运行约 5 分钟（抓取 174 个仓库 + 50 个健康度数据 + 30 个项目 LLM 分析）。后续增量更新很快。

### 方式二：查看效果截图

![Web页面效果](图片/图片2.png)

---

## 4. TRAE 实践过程

### 开发全流程

整个项目经历 **3 个核心 Session**，从基础 Trending 抓取逐步升级为完整的三模式日报平台。

---

#### 阶段一：需求深挖 + 架构决策（Session 1）

使用 `/grill-me` Skill 进行了 **19 轮结构化盘问**，从"评分体系太简陋"这个模糊痛点出发，逐步确认了完整技术方案：

- 7 维健康度数据源（issues/PR/contributors/releases/commits/activity/maturity）
- 基础日报 6 板块 + AI 垂类 5 板块 + 自定义动态板块
- Flask Web + Jinja2 + 前端异步刷新的技术选型
- 自然语言解析的 **4 层 LLM 降级防御体系**（规则优先 → LLM → 无效降级 → 元模板兜底）
- 32 个话题模板覆盖 AI/金融/开发/安全/语言生态/云计算等方向

> ![grill-me 决策记录](图片/图片3.png)

🆔 `.1690425231940170:fef5f7d58d170ac9077f5dd661eef414_6a37f9223c4a289115686da3.6a3881c13c4a289115686da6.6a3881c0836b5ba98b80445e:Trae CN.T(2026/6/22 08:28:49)`

---

#### 阶段二：核心模块全线开发（Session 2）

基于决策文档，用 TRAE 一次性实现了 **10 个核心模块**：

| 模块 | 文件 | 功能 |
|------|------|------|
| 增强数据抓取 | `src/fetcher/extra_api.py` | GitHub API 7 维度数据采集 |
| 多维评分系统 | `src/processor/scoring.py` | 5 子维度 + 6 大板块评分公式 |
| 6板块日报 | `src/reporter/daily_report.py` | 深色主题 HTML 日报 |
| 自定义解析器 | `src/processor/custom_parser.py` | 自然语言 → 结构化查询（规则+LLM+降级） |
| 自定义日报 | `src/reporter/custom_report.py` | 动态板块 HTML 生成 |
| Web 服务器 | `web/app.py` | Flask 服务 + 2 TAB 切换 + 自定义 API |
| 数据库迁移 | `src/storage/db.py` | 7 个新字段 + 自动迁移 |
| 主流程集成 | `src/main.py` | Pipeline 串联 + 邮件推送 |

> ![TRAE 编码过程](图片/图片1.png)

🆔 `.1690425231940170:2a4d7a29050fca827aba687abea8148b_6a37f9223c4a289115686da3.6a38823f3c4a289115686def.6a38823e836b5ba98b804460:Trae CN.T(2026/6/22 08:30:55)`

---

#### 阶段三：联调测试 + 部署（Session 3）

- 配置 GitHub Token + DeepSeek API Key + QQ 邮箱
- 全流程 Pipeline 验证：抓取 → 去重 → 分类 → 7维评分 → LLM分析 → 三份日报 → 邮件推送
- 修复 Token 占位符误拦截、路径 Emoji 编码、Flask 超时崩溃等 5 个 Bug
- Web UI 美化：毛玻璃导航、卡片悬浮动画、渐变徽章、响应式布局

🆔 `.1690425231940170:f177269fac319e18e5cd6eb534ee81f5_6a37f9223c4a289115686da3.6a3882e33c4a289115686e39.6a3882e3836b5ba98b804462:Trae CN.T(2026/6/22 08:33:39)`

---

### 核心架构亮点

```
用户浏览器（2 TAB）
  │
  ├─ TAB 1: 基础日报 ← 6板块评分引擎 → 7维健康度数据
  └─ TAB 2: 自定义  ← 自然语言解析器 → 32话题模板 + 多厂商LLM
       │
       └─ 输入"量化交易" → 规则匹配（毫秒级）→ 金融日报
       └─ 输入"大模型"   → AI垂类评分引擎 → 模型/Agent/评测维度的AI日报
       └─ 输入新颖话题   → LLM解析 + json_object → 动态板块生成
       └─ LLM失败       → 关键词降级 → 元模板兜底
```

### 关键技术决策

1. **规则优先 + LLM 兜底**：32 个常用话题走毫秒级规则匹配，冷门话题才调 DeepSeek
2. **response_format: json_object**：强制 LLM 输出合法 JSON，避免格式错误
3. **元模板降级**：LLM 失败时自动拼接 `{话题} 热门 / {话题} 新星 / {话题} 精品 / 数据看板`
4. **Token 智能跳过**：识别占位符 Token → 自动跳过 API 请求 → 优雅降级不崩溃
5. **数据库自动迁移**：新增 7 个评分字段，`init_db()` 自动检测并追加，不丢数据

---

### 已通过的社区报名帖链接

> `[填写你的报名帖链接]`

---

## 📊 项目数据

| 指标 | 数值 |
|------|------|
| 新增/修改文件 | 10+ 个，~2500 行 |
| 健康度维度 | 7 个（issues/PR/contributors/releases/commits/activity/maturity） |
| 基础日报板块 | 6 个 |
| 自定义话题模板 | 32 个 |
| 每日分析仓库 | 170+ |
| DeepSeek 分析 | 30 个项目/天 |
| 响应速度 | 首页秒开，自定义查询 150-500ms |
| 技术栈 | Python + Flask + SQLite + BeautifulSoup + DeepSeek API + GitHub REST API |

---
