#!/usr/bin/env bash
# 把 whisper 输出的 .srt 压缩成按分钟合并的 .compact.txt,并过滤常见幻觉行(逻辑在 compact.py,网页工作台也直接调用它)
# 用法: compact.sh <字幕.srt> [输出文件,默认同名 .compact.txt]
# 输出格式: 每行 "[HH:MM] 该分钟内的全部文本"(方括号里是 时:分,例如 [01:41] = 1 小时 41 分),空白分钟省略
set -euo pipefail
in="${1:?用法: compact.sh <字幕.srt> [输出文件]}"
out="${2:-${in%.srt}.compact.txt}"
[ -f "$in" ] || { echo "错误: 找不到文件 $in" >&2; exit 1; }
python3 "$(cd "$(dirname "$0")" && pwd)/compact.py" "$in" "$out"
