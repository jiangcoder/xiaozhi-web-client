# 使用Python 3.11基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY requirements.txt .
COPY app.py .
COPY proxy.py .
COPY templates/ templates/
COPY static/ static/

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口
EXPOSE 5001 5002

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动命令
CMD ["python", "app.py"] 