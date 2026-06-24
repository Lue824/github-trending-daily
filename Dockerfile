# Hugging Face Spaces Dockerfile
# 文档：https://huggingface.co/docs/hub/spaces-sdks-docker

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 系统依赖（lxml 编译需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# HF Spaces 文件系统大部分只读，可写目录：/data
# 将数据目录指向 /data（持久化数据由 git 仓库提供，运行时只读）
ENV DATA_DIR=/data
RUN mkdir -p /data/reports /data/raw /data/readmes

# 如果仓库里有预生成的日报和数据库，复制到可写目录
# （HF Spaces 每次 rebuild 会重置非 /data 目录，但 git 仓库内容在镜像里）
# 这里把仓库内的 data/reports 和 trending.db 复制到 /data，保证可读可写
RUN if [ -d /app/data/reports ]; then cp -r /app/data/reports/* /data/reports/ 2>/dev/null || true; fi
RUN if [ -f /app/data/trending.db ]; then cp /app/data/trending.db /data/trending.db 2>/dev/null || true; fi
RUN if [ -f /app/data/repos.json ]; then cp /app/data/repos.json /data/repos.json 2>/dev/null || true; fi
RUN if [ -f /app/data/subscription.json ]; then cp /app/data/subscription.json /data/subscription.json 2>/dev/null || true; fi

# HF Spaces 默认端口 7860
ENV PORT=7860
ENV FLASK_DEBUG=0
EXPOSE 7860

# 用 gunicorn 启动（生产级 WSGI 服务器）
# HF Spaces 推荐用 gunicorn + 同步 worker
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]
