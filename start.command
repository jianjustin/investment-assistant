#!/bin/zsh
set -eu

cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print -u2 '缺少 Python 环境，请先按 README 安装依赖。'
  exit 1
fi

# 本地入口先加载配置再导入服务，避免继承旧调度开关或过早读取端口。
exec .venv/bin/python scripts/start_local.py
