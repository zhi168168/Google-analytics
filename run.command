#!/bin/zsh

set -u
cd "$(dirname "$0")"

echo "正在查询 GA4 昨日活跃用户数..."
echo

if .venv/bin/python ga4_yesterday_users.py; then
  echo
  echo "查询完成，正在打开结果表..."
  open yesterday_users.csv
else
  echo
  echo "查询未全部成功，请查看上方提示。"
fi

echo
read "?按回车键关闭窗口..."
