#!/bin/bash
# 双击启动课程笔记工作台(Mac)。关闭这个窗口会停止工作台。
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3。请先安装:在终端运行 xcode-select --install,或从 https://www.python.org 下载安装。"
  read -r -p "按回车关闭"; exit 1
fi
python3 -m web "$@"
status=$?
if [ $status -ne 0 ]; then read -r -p "工作台异常退出(代码 $status),按回车关闭"; fi
