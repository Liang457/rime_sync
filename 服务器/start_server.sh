#!/bin/bash
# Rime服务器启动脚本

set -e

cd "$(dirname "$0")"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "错误: 虚拟环境不存在，请先运行: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查Python依赖
if ! python -c "import flask" 2>/dev/null; then
    echo "错误: Flask未安装，请安装依赖: pip install -r requirements.txt"
    exit 1
fi

# 创建必要的目录
mkdir -p logs backups sync runtime config

# 启动服务器
echo "启动rime-server..."
echo "监听端口: 10032"
echo "日志文件: logs/server.log"

exec python server.py