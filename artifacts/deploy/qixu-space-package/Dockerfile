# 多阶段构建：前端 Node 构建 → Python 运行（FastAPI + React 静态 + SQLite）
FROM node:24-slim AS webbuild
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
# 用 pip 安装项目自身（uv.lock 仅作本地锁定参考；镜像内以 pyproject 依赖为准）
RUN pip install --no-cache-dir .
COPY src ./src
COPY data ./data
COPY scripts ./scripts
COPY --from=webbuild /build/web/dist ./web/dist
ENV QIXU_RUNTIME_DIR=/app/runtime
EXPOSE 8000
# 持久卷挂载 /app/runtime 与 /app/artifacts（如需保留运行证据）；PORT 兼容 HF Spaces/Render 注入
CMD ["sh", "-c", "uvicorn scripts.serve_api:app --host 0.0.0.0 --port ${PORT:-8000}"]
