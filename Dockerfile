FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY src/ ./src/
COPY config/ ./config/
COPY .env.template ./

# 创建必要的目录
RUN mkdir -p data logs

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 健康检查
HEALTHCHECK --interval=5m --timeout=30s --start-period=5s --retries=3 \
    CMD python src/main.py --mode health || exit 1

# 默认命令
CMD ["python", "src/main.py", "--mode", "continuous"] 