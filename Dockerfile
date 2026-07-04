# 多阶段构建：阶段 1 编译前端静态资源，阶段 2 组装 Python 运行时。
# API 与调度器共用本镜像，部署时用不同启动命令区分（见 docs/deployment-sealos.md）。

FROM node:22-alpine AS web-build
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.14-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY investment_assistant/ investment_assistant/
COPY migrations/ migrations/
# static_files.STATIC_DIR 解析为 <包根>/web/dist
COPY --from=web-build /build/dist web/dist

# runtime_paths 的运行期可写目录：run log 与 filings（filings 建议挂持久卷）
RUN mkdir -p /opt/hermes-investment-assistant/logs /srv/investment-assistant/filings

# 容器内绑定 0.0.0.0 是常态（对外暴露由平台 Ingress 决定）；
# fail-closed 仍然生效：未设置 SERVER_PWD 时服务拒绝启动。
ENV HERMES_DASHBOARD_HOST=0.0.0.0 \
    HERMES_DASHBOARD_PORT=8787 \
    HERMES_DASHBOARD_ALLOW_PUBLIC=1

EXPOSE 8787

# migrate 幂等（内部 ledger 去重），配置了 DB 时每次启动先补齐 schema 再起服；
# 未配 DB 时跳过 migrate 以 degraded 模式启动（与应用降级语义一致）
CMD ["sh", "-c", "if [ -n \"$INVESTMENT_ASSISTANT_DATABASE_URL\" ]; then python -m investment_assistant.migrate; fi && python -m investment_assistant.api.server"]
