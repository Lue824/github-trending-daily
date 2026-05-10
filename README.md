# 🚀 GitHub Trending Daily

每天自动抓取 GitHub 热门/高星项目，生成 Markdown 日报 + 推送到 QQ 邮箱，持续感知 GitHub 热点。

## 功能

- **多源抓取**：GitHub Trending 页面 + GitHub Search API + GraphQL
- **智能标签**：自动识别机器学习、深度学习、大模型/AI、具身智能项目
- **历史对比**：标记连续在榜项目，展示热度趋势
- **日报推送**：生成 Markdown 日报，HTML 邮件推送到 QQ 邮箱
- **月度报告**：每月自动生成月度趋势分析（热门语言、增速最快、持续热门）
- **长期存储**：SQLite 存储 30 天数据，自动清理

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

编辑 `.env`：

```ini
# GitHub Token（可选，提高 API 限额）
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# QQ 邮箱
QQ_EMAIL=your_qq@qq.com

# QQ 邮箱授权码（设置 → 账户 → POP3/SMTP 服务 → 生成授权码）
QQ_EMAIL_AUTH_CODE=xxxxxxxxxxxx

# 接收邮箱
RECEIVER_EMAIL=your_qq@qq.com
```

> QQ 邮箱授权码获取方式：登录 QQ 邮箱 → 设置 → 账户 → POP3/IMAP/SMTP 服务 → 开启 SMTP 服务 → 生成授权码

### 3. 本地运行

```bash
python src/main.py
```

### 4. 部署到 GitHub Actions（推荐）

1. 将代码推送到 GitHub
2. 在仓库 Settings → Secrets and variables → Actions 中添加以下 Secrets：
   - `GH_TOKEN`：GitHub Personal Access Token
   - `QQ_EMAIL`：你的 QQ 邮箱
   - `QQ_EMAIL_AUTH_CODE`：QQ 邮箱授权码
   - `RECEIVER_EMAIL`：接收邮件的邮箱
3. GitHub Actions 会每天北京时间 09:00 自动运行

也可以手动触发：Actions → GitHub Trending Daily Report → Run workflow

## 项目结构

```
github-trending-daily/
├── src/
│   ├── fetcher/           # 数据抓取
│   │   ├── trending.py    #   GitHub Trending 爬虫
│   │   └── search_api.py  #   GitHub Search API
│   ├── processor/         # 数据处理
│   │   ├── dedup.py       #   去重合并
│   │   └── categorize.py  #   分类排序
│   ├── storage/
│   │   └── db.py          # SQLite 持久化
│   ├── reporter/
│   │   └── markdown.py    # Markdown/HTML 报告
│   ├── notifier/
│   │   └── email_sender.py # QQ 邮箱推送
│   └── main.py            # 主入口
├── .github/workflows/
│   └── daily.yml          # GitHub Actions 定时任务
├── config.py              # 配置文件
├── requirements.txt
└── README.md
```

## 日报内容

- 🔥 Trending 今日榜单 Top 15
- ⭐ 30天内新星项目 Top 15
- 🤖 AI/ML/具身智能 重点关注 Top 20
- 📊 编程语言分布
- 🏷️ 连续在榜项目（🔥 streak 标记）
- 📈 统计摘要

## 月度报告内容

- 🏆 月度持续热门项目
- 🚀 月度增速最快项目
- 🌐 热门编程语言排行
