#!/usr/bin/env bash
# 集成测试:用仓库自带的合成示例视频跑完整流水线(CI 用 tiny.en 模型,几十秒),再校验示例总结
# 用法: bash tests/run_pipeline_demo.sh   环境变量: WHISPER_MODEL(默认 tiny.en,本机可设 large-v3-turbo)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cp -r "$root/examples/demo/." "$work/"
rm -rf "$work/画面" "$work/课程视频/"*.srt "$work/课程视频/"*.txt "$work/课程视频/"*.json "$work/课程视频/"*.md
export COURSE_ROOT="$work" WHISPER_MODEL="${WHISPER_MODEL:-tiny.en}"
bash "$root/工具/prepare.sh" "DEMO1001 - 01 Jan 26-s1-demo.mp4" en
g="$work/课程视频/DEMO1001 - 01 Jan 26-s1-demo.grounded.md"
grep -q "prime path" "$g" || { echo "FAIL: 转写里没有 'prime path'"; exit 1; }
grep -q "📄 t=.*p[0-9]/6 DEMO1001" "$g" || { echo "FAIL: PDF 页码匹配没有生效"; exit 1; }
python3 "$root/工具/check_summary.py" "$work/总结/DEMO1001/DEMO1001 - 01 Jan 26-s1-demo.md"
python3 "$root/工具/course_meta.py" "DEMO1001 - 01 Jan 26-s1-demo.mp4" --json | grep -q '"week": 1' || { echo "FAIL: course_meta 周次不对"; exit 1; }
echo "PASS: pipeline demo"
