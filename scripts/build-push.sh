#!/usr/bin/env bash
# 构建并推送镜像到 Docker Hub（docker.io/jianjustin/investment-assistant）。
# 用法：scripts/build-push.sh [tag]
#   tag 默认 latest；同时总会附打 git short-sha tag 供回滚。
# 可覆盖：IMAGE_REPO（默认 jianjustin/investment-assistant）、IMAGE_PLATFORM（默认 linux/amd64）。
set -euo pipefail

REPO="${IMAGE_REPO:-jianjustin/investment-assistant}"
TAG="${1:-latest}"
# Sealos 节点是 amd64；Apple Silicon 本机必须交叉构建，否则镜像在云端跑不起来
PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"

cd "$(dirname "$0")/.."
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"

echo ">> buildx 构建并推送 ${REPO}:${TAG} + :${GIT_SHA}（${PLATFORM}）"
docker buildx build \
  --platform "${PLATFORM}" \
  -t "docker.io/${REPO}:${TAG}" \
  -t "docker.io/${REPO}:${GIT_SHA}" \
  --push \
  . || { echo "!! 构建/推送失败——若未登录请先执行: docker login -u jianjustin"; exit 1; }

echo ">> 完成: docker.io/${REPO}:${TAG}（回滚可用 :${GIT_SHA}）"
