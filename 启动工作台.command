#!/bin/bash
# 双击启动总结工作台(macOS)。第一次会自动装好缺的工具,然后在浏览器打开 http://127.0.0.1:8770
# 工作台运行期间这个窗口要一直开着;用完关掉窗口(或按 Ctrl+C)就停了。
# Double-click to start the Lecture Workbench (macOS). The first run installs whatever is missing,
# then opens http://127.0.0.1:8770 in your browser. Keep this window open while you use it; close it to stop.
cd "$(dirname "$0")" || exit 1
bash workbench/setup.sh
code=$?
if [ "$code" -ne 0 ]; then
  echo
  read -n 1 -s -r -p "按任意键关闭这个窗口 / Press any key to close this window"
  echo
fi
exit "$code"
