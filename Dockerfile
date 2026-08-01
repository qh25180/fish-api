# ─── QHAPI 镜像构建 ────────────────────────────────────────────
# 基础镜像：Python 3.13 slim（依赖均为纯 Python / 自带 wheel，无需编译工具）
FROM python:3.13-slim

WORKDIR /app

# 先复制依赖清单并安装，利用 Docker 层缓存，源码变更时不必重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码（novels/、.env、scripts/ 已在 .dockerignore 中排除）
COPY . .

# 应用监听端口
EXPOSE 8000

# 使用 python main.py 直接启动（自动读取 .env 配置与上传超时）
CMD ["python", "main.py"]
