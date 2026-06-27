---
title: GitHub Trending Daily
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🚀 GitHub Trending Daily

每天自动抓取 GitHub 热门/高星项目，生成 6 板块深度 HTML 日报，并提供自定义话题搜索 + 多厂商 LLM 深度中文分析 + 邮件订阅推送 + Cloudflare Tunnel 公网访问的完整 Web 应用。

## 功能特性

### 📊 基础日报（6 板块）
- **🧨 正在爆发** — 短期星标增速最快的项目
- **🏆 质量标杆** — 综合维护活跃度、工程成熟度、社区参与度的优质项目
- **🚀 潜力新星** — 90 天内创建且增长势头强劲的新项目
- **⚠️ 热度陷阱** — 热度高但健康度差的项目（避坑指南）
- **🤖 AI 雷达** — AI/ML/具身智能方向重点项目
- **📈 数据看板** — 编程语言分布、连续在榜、统计摘要

### 🔧 自定义话题日报
- **40+ 话题模板库**：量化交易、AI Agent、游戏开发、嵌入式、机器人等
- **4 层解析防御**：规则匹配 → LLM 解析 → 中文降级 → 兜底处理
- **3 级搜索流程**：基础数据库 → GitHub 全库搜索 → 高价值替代
- **多厂商 LLM 支持**：DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / Moonshot（用户自带 Key）

### 📧 订阅与推送
- 基础日报 / 自定义话题订阅
- 邮件加密存储（Fernet）+ 退订 token 校验（防 IDOR）
- SMTP 邮件推送（兼容任意邮箱服务商）
- tunnel URL 变更自动通知

### 🛡️ 安全与可靠性
- 全链路 XSS 转义（`html_safe.py` 工具集）
- IP 速率限制 + 结果缓存（10 分钟 TTL）
- SQLite WAL 模式 + 参数化查询（无 SQL 注入）
- 加密主密钥 `data/.secret_key`（不入版本库）
- Docker 非 root 用户 + HEALTHCHECK

### 🌐 部署形态
- **Cloudflare Tunnel** + **GitHub Pages 跳转**：内网服务公网访问
- **Hugging Face Spaces**：Docker 镜像部署
- **GitHub Actions**：每日定时任务
- **本地开发**：Flask + Werkzeug

## 快速开始

### 1. 克隆并安装

```bash
git clone <your-repo-url>
cd GitHub_Trending_Projects_Summary
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`（详见 [`.env.example`](.env.example)）：

```ini
# 数据获取（可选，提高 GitHub API 限额）
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# 邮件推送（订阅功能必填）
QQ_EMAIL=your_email@example.com
QQ_EMAIL_AUTH_CODE=xxxxxxxxxxxx
RECEIVER_EMAIL=your_email@example.com

# LLM 深度分析（可选）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx

# Web 服务（可选）
FLASK_DEBUG=0
PORT=5000
DATA_DIR=data
```

### 3. 启动 Web 服务

```bash
# 开发模式（自动加载修改）
python src/main.py --web

# 或生产 WSGI（推荐）
gunicorn --bind 0.0.0.0:7860 --workers 2 --threads 4 --timeout 120 wsgi:application
```

访问 `http://localhost:5000`

### 4. 运行每日定时任务

```bash
# 一次性运行（抓取 + 处理 + 报告 + 邮件推送）
python src/main.py
```

### 5. 启动 URL 监控守护（可选，配合 Cloudflare Tunnel）

```bash
python src/notifier/url_monitor.py --daemon -v
```

## API 文档

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页（Web 应用） |
| `/api/daily` | GET | 当日基础日报 HTML |
| `/api/refresh` | GET | 强制刷新日报（返回最新一份） |
| `/api/custom` | POST | 自定义话题日报（body: `{query, api_key, provider}`） |
| `/api/subscribe` | POST | 订阅日报（body: `{type, email, topic?, keywords?, api_key?}`） |
| `/api/unsubscribe` | POST/GET | 退订（body: `{token}` 或 `{email}`，后者会发确认邮件） |
| `/api/subscriptions` | GET | 订阅者统计（人数，不展示明细） |
| `/api/history` | GET | 历史报告列表 |
| `/reports/<filename>` | GET | 历史报告文件（包裹完整 HTML 文档壳） |
| `/api/status` | GET | 系统状态（加密/订阅/报告数） |
| `/api/tunnel_status` | GET | tunnel 监控状态 |

## 项目结构

```
GitHub_Trending_Projects_Summary/
├── src/
│   ├── fetcher/                  # 数据抓取
│   │   ├── trending.py           #   GitHub Trending 爬虫
│   │   ├── search_api.py         #   GitHub Search API + README
│   │   └── extra_api.py          #   仓库健康度数据（contributors/releases）
│   ├── processor/                # 数据处理
│   │   ├── categorize.py         #   分类打标签
│   │   ├── scoring.py            #   5 维度评分（爆发/质量/潜力/陷阱/AI）
│   │   ├── ai_scoring.py         #   AI 雷达评分
│   │   ├── dedup.py              #   去重合并
│   │   ├── translator.py         #   LLM 翻译兜底
│   │   ├── llm_summarize.py      #   LLM 摘要/趋势分析
│   │   ├── describe_cn.py        #   中文描述生成（6 维度规则）
│   │   └── custom_parser.py      #   自定义话题解析（4 层防御）
│   ├── reporter/                 # HTML 报告生成
│   │   ├── daily_report.py       #   基础 6 板块日报
│   │   ├── custom_report.py      #   自定义话题日报
│   │   ├── ai_report.py          #   AI 深度日报
│   │   ├── email_template.py     #   邮件 HTML 模板
│   │   ├── markdown.py           #   月度 Markdown 报告
│   │   └── _shared.py            #   共享工具（锚点/排名徽章）
│   ├── storage/
│   │   └── db.py                 #   SQLite 持久化（WAL）
│   ├── notifier/
│   │   ├── email_sender.py       #   SMTP 邮件推送
│   │   ├── url_monitor.py        #   Cloudflare Tunnel 监控守护
│   │   └── notify_url_change.py  #   tunnel URL 变更通知
│   ├── utils/
│   │   ├── crypto.py             #   Fernet 加密（订阅邮箱/API Key）
│   │   └── html_safe.py          #   HTML 转义工具（esc/safe_href/safe_text_br）
│   ├── pipeline.py               #   数据管道（抓取→处理→存储→报告→推送）
│   └── main.py                   #   主入口（--web 启动 Web 服务）
├── web/
│   └── app.py                    #   Flask Web 应用（首页 + API）
├── .github/workflows/daily.yml   #   GitHub Actions 每日定时任务
├── config.py                     #   配置加载（.env 解析）
├── wsgi.py                       #   生产 WSGI 入口
├── Dockerfile                    #   Docker 镜像（非 root + HEALTHCHECK）
├── render.yaml                   #   Render 部署配置
├── index.html                    #   GitHub Pages 跳转页
├── redirect.json                 #   当前 tunnel URL（自动同步）
└── requirements.txt              #   Python 依赖
```

## 部署

### Hugging Face Spaces（推荐）

1. 推送代码到 GitHub
2. 在 HF Spaces 创建 Docker 类型空间，关联 GitHub 仓库
3. HF Spaces 自动构建并部署到 `https://<user>-github-trending-daily.hf.space`
4. 配置 Secrets：`GH_TOKEN`、`QQ_EMAIL`、`QQ_EMAIL_AUTH_CODE`、`RECEIVER_EMAIL`、`DEEPSEEK_API_KEY`、`HF_TOKEN`

### GitHub Actions（每日定时）

1. 推送代码到 GitHub
2. 在仓库 Settings → Secrets and variables → Actions 添加 Secrets：
   - `GH_TOKEN` — GitHub Token
   - `QQ_EMAIL` / `QQ_EMAIL_AUTH_CODE` / `RECEIVER_EMAIL` — 邮件配置
   - `DEEPSEEK_API_KEY` — LLM Key
   - `HF_TOKEN` — Hugging Face Token（同步到 HF Spaces）
3. Actions 每天北京时间 07:00 自动运行（也可手动触发）

### Cloudflare Tunnel + GitHub Pages 跳转

本地开发但需公网访问时：

1. 启动 tunnel 守护：`python src/notifier/url_monitor.py --daemon -v`
2. tunnel URL 变化时自动同步到 GitHub Pages 的 `redirect.json`
3. 公网用户访问 GitHub Pages 跳转页 → 自动重定向到当前 tunnel URL

## 技术栈

- **后端**：Python 3.11、Flask 3.0、gunicorn
- **数据**：SQLite（WAL）、GitHub REST API v3、Search API
- **LLM**：DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / Moonshot
- **部署**：Docker、Hugging Face Spaces、GitHub Actions、Cloudflare Tunnel
- **邮件**：SMTP SSL（兼容任意邮箱服务商）
- **加密**：cryptography Fernet（AES-128-CBC + HMAC-SHA256）

## 安全说明

- 所有用户输入（GitHub API 数据、用户查询）经 HTML 实体转义后渲染
- 订阅邮箱与 API Key 用 Fernet 加密存储
- 退订需 token 校验（防 IDOR 恶意退订）
- `/api/custom` 限流（每 IP 每分钟 5 次）+ 10 分钟缓存
- Docker 非 root 用户运行，`.dockerignore` 排除敏感文件
- CI 不提交订阅数据与数据库到公开仓库

## License

MIT
