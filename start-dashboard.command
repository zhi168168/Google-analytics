#!/bin/zsh

set -u
cd "$(dirname "$0")"

echo "正在启动 GA4 可视化仪表盘..."
echo
.venv/bin/python dashboard.py

echo
echo "仪表盘已停止。"
read "?按回车键关闭窗口..."
