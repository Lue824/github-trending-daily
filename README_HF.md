# HF Spaces 元数据
---
title: GitHub Trending Daily
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# GitHub Trending Daily

AI 驱动的 GitHub 热门项目分析平台，每日自动抓取 GitHub Trending，提供：

- 📊 **基础日报**：6 板块多维评价（热度/质量/爆发/陷阱检测等）
- 🔧 **自定义日报**：输入话题生成专属日报（支持 32 话题模板 + LLM 动态解析）
- 📬 **邮件订阅**：每日定时推送基础/自定义日报

## 工作原理

- **数据抓取**：GitHub Actions 每天 UTC 23:00 运行 `src/main.py`，抓取数据并生成日报文件，提交到仓库
- **Web 展示**：Hugging Face Spaces 运行 Flask 应用，从仓库内预生成的文件读取数据（毫秒级响应，不消耗 CPU 配额）
- **自定义查询**：从 SQLite 数据库读取当天 repos，本地匹配生成（不触发完整抓取）

## 自定义日报

支持用户填入自己的 LLM API Key（个人化，不消耗项目方额度）：
- DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / Moonshot

## 技术栈

- Flask + SQLite + GitHub REST API
- DeepSeek LLM 大模型分析
- 4 层 LLM 降级防御体系
- 32 个话题模板的自然语言解析
