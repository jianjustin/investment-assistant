#!/usr/bin/env bash
#
# 本地 → NUC 部署脚本（在 Mac 上运行）。
#
# 流程（git 方式）：
#   1. 本地工作区必须干净且已 commit
#   2. push 当前分支到 GitHub(origin)
#   3. SSH 到 NUC，git pull --ff-only 拉取最新代码
#   4. 在 NUC 上跑 deploy/install.sh（重建 venv / 迁移 / 构建前端 / 安装 systemd）
#   5. 重启 dashboard 服务并打印状态
#
# 用法：
#   deploy/push-to-nuc.sh                 # 完整部署
#   deploy/push-to-nuc.sh --skip-install  # 只 pull + 重启，不跑 install.sh（快速）
#   deploy/push-to-nuc.sh --no-restart    # 部署但不重启服务
#   deploy/push-to-nuc.sh --allow-dirty   # 允许工作区有未提交改动（跳过干净检查，仍只部署已 push 的提交）
#
# 可用环境变量覆盖默认值：
#   REMOTE_HOST  (默认 192.168.0.103)
#   REMOTE_USER  (默认 jianjustin)
#   REMOTE_DIR   (默认 /home/jianjustin/workspaces/investment-assistant)
#   SERVICE      (默认 hermes-investment-dashboard.service)

set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-192.168.0.103}"
REMOTE_USER="${REMOTE_USER:-jianjustin}"
REMOTE_DIR="${REMOTE_DIR:-/home/jianjustin/workspaces/investment-assistant}"
SERVICE="${SERVICE:-hermes-investment-dashboard.service}"

SKIP_INSTALL=0
NO_RESTART=0
ALLOW_DIRTY=0
for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=1 ;;
    --no-restart)   NO_RESTART=1 ;;
    --allow-dirty)  ALLOW_DIRTY=1 ;;
    -h|--help)      grep '^#' "$0" | sed 's/^# \{0,1\}//' ; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

# 进入仓库根目录（脚本位于 deploy/ 下）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

c_ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
c_step() { printf '\033[36m▶ %s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
c_step "本地仓库: $REPO_ROOT  分支: $BRANCH"

# 1) 干净 + 已提交检查
if [[ "$ALLOW_DIRTY" -eq 0 && -n "$(git status --porcelain)" ]]; then
  c_err "工作区有未提交改动。请先 commit，或加 --allow-dirty（仅部署已 push 的提交）。"
  git status --short
  exit 1
fi

# 2) push 当前分支
c_step "推送 $BRANCH → origin"
git push origin "$BRANCH"
c_ok "已推送到 GitHub"

# 3-5) 在 NUC 上执行（-t 分配 TTY 以便 sudo 输入密码）
c_step "SSH 部署到 ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"

# 组装远程脚本：本地变量在此展开（$REMOTE_DIR/$BRANCH/...）；
# 需要远程执行的命令替换用 \$ 转义，避免在本地被求值。
REMOTE_SCRIPT=$(cat <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR"

echo "▶ git fetch & pull --ff-only ($BRANCH)"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
echo "  当前 HEAD: \$(git rev-parse --short HEAD)  \$(git log -1 --pretty=%s)"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  echo "▶ 运行 deploy/install.sh (需要 sudo)"
  sudo bash deploy/install.sh
else
  echo "! 跳过 install.sh (--skip-install)"
fi

if [[ "$NO_RESTART" -eq 0 ]]; then
  echo "▶ 重启 $SERVICE"
  sudo systemctl restart "$SERVICE"
  sleep 1
  systemctl --no-pager --lines=0 status "$SERVICE" | head -5 || true
else
  echo "! 跳过重启 (--no-restart)"
fi
REMOTE
)

# 关键：不要把脚本重定向进 ssh 的 stdin，否则 ssh 不分配伪终端，
# 远程 sudo 会报 "A terminal is required to authenticate"。
# 改为把脚本 base64 编码后作为参数传过去，远程解码再交给 bash 执行；
# ssh 的 stdin 保持为本地终端，-t 才能正常分配 pty 供 sudo 读取密码。
REMOTE_B64="$(printf '%s' "$REMOTE_SCRIPT" | base64)"
ssh -t "${REMOTE_USER}@${REMOTE_HOST}" "echo '$REMOTE_B64' | base64 --decode | bash"

c_ok "部署完成。NUC 服务: http://${REMOTE_HOST} (dashboard)"
