#!/usr/bin/env bash
# rime_server 启动脚本（Linux / systemd 手动运行）
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python run.py
