# ProManager：单容器内 FastAPI + 已构建的前端静态资源（访问 :8000）
# 构建：在仓库根目录 docker build -t promanager .
# 运行：docker run --env-file backend/.env -p 8000:8000 -v promanager-data:/app/backend/data promanager

FROM node:20-alpine AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY --from=frontend-build /src/dist /app/frontend/dist

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# 后台定时同步与 SQLite 锁：生产请保持单 worker，或用外部 cron + BACKGROUND_SYNC_ENABLED=false
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
