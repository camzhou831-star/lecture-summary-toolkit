#!/usr/bin/env bash
# 一键预处理一节录播:转写(VAD+术语表)‖抓帧 → compact → 帧去重 → OCR → bundle/讲义稿
# 用法: prepare.sh <视频文件名或路径> [语言码,默认 en] 
#   文件名不带路径时依次在 课程视频/ 和 ~/Downloads/ 找;在 Downloads 找到会先移入 课程视频/
#   工作目录 = COURSE_ROOT,未设置时为本脚本所在 工具/ 的上级目录
#   环境变量: FORCE=1 忽略已有产物全部重做;FRAME_MODE=12s 抓帧模式(默认 12s);NO_VAD=1 / GLOSSARY=<文件> 透传给 transcribe.sh
#   跳过规则: 只有"转写"和"抓帧"两步在已有产物时跳过;compact、去重、OCR(增量)、bundle 每次都重跑(都只要几秒)
# 产出(全部在 课程视频/ 与 画面/):
#   <名>.srt/.txt/.compact.txt  画面/<名>/*.jpg + ocr.json  <名>.bundle.json  <名>.grounded.md
set -euo pipefail
TOOLS="$(cd "$(dirname "$0")" && pwd)"
ROOT="${COURSE_ROOT:-$(dirname "$TOOLS")}"   # 默认为 工具/ 的上级目录,可用 COURSE_ROOT 覆盖
arg="${1:?用法: prepare.sh <视频文件名或路径> [语言码]}"
lang="${2:-en}"
mode="${FRAME_MODE:-12s}"

mkdir -p "$ROOT/课程视频"
if [ -f "$arg" ]; then video="$arg"
elif [ -f "$ROOT/课程视频/$arg" ]; then video="$ROOT/课程视频/$arg"
elif [ -f "$HOME/Downloads/$arg" ]; then
  [ -e "$ROOT/课程视频/$arg" ] && { echo "错误: 课程视频/ 已有同名文件 $arg,不覆盖;请先处理" >&2; exit 1; }
  echo "== 在 Downloads 找到,移入 课程视频/"; mv -n "$HOME/Downloads/$arg" "$ROOT/课程视频/"; video="$ROOT/课程视频/$arg"
else echo "错误: 找不到 $arg(查过 课程视频/ 与 ~/Downloads/)" >&2; exit 1; fi

case "$video" in "$ROOT/课程视频/"*) ;; *)
  [ -e "$ROOT/课程视频/$(basename "$video")" ] && { echo "错误: 课程视频/ 已有同名文件 $(basename "$video"),不覆盖;请先处理" >&2; exit 1; }
  echo "== 视频不在 课程视频/,移入以保持产物集中"; mv -n "$video" "$ROOT/课程视频/"; video="$ROOT/课程视频/$(basename "$video")";; esac

mkdir -p "$ROOT/课程视频" "$ROOT/画面" "$ROOT/总结"
base="${video%.*}"; name="$(basename "$base")"
frames="$ROOT/画面/$name"
is_video=1; ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$video" | grep -q video || is_video=0
t0=$(date +%s)
echo "== 预处理: $name (语言 $lang, 抓帧模式 $mode, 有画面: $is_video)"

pids=()
if [ "${FORCE:-0}" = 1 ] || [ ! -s "$base.srt" ]; then
  echo "== [1/5] 转写 (后台)"; bash "$TOOLS/transcribe.sh" "$video" "$lang" > "$base.transcribe.log" 2>&1 & pids+=($!)
else echo "== [1/5] 转写: 已有 $name.srt,跳过(FORCE=1 可重做)"; fi
if [ "$is_video" = 1 ]; then
  if [ "${FORCE:-0}" = 1 ] || [ -z "$(ls "$frames" 2>/dev/null | grep -c '\.jpg$' || true)" ] || [ "$(ls "$frames" 2>/dev/null | grep -c '\.jpg$')" = 0 ]; then
    echo "== [2/5] 抓帧 (后台)"; bash "$TOOLS/extract_frames.sh" "$video" "$mode" "$frames" > "$base.frames.log" 2>&1 & pids+=($!)
  else echo "== [2/5] 抓帧: 画面/$name 已有帧,跳过(FORCE=1 可重做)"; fi
fi
fail=0
for p in ${pids[@]+"${pids[@]}"}; do wait "$p" || fail=1; done
if [ "$fail" = 1 ]; then echo "错误: 转写或抓帧失败,看 $base.transcribe.log / $base.frames.log" >&2; exit 1; fi
tail -n 2 "$base.transcribe.log" 2>/dev/null | sed 's/^/   /' || true
tail -n 1 "$base.frames.log" 2>/dev/null | sed 's/^/   /' || true

echo "== [3/5] compact"; bash "$TOOLS/compact.sh" "$base.srt"
if [ "$is_video" = 1 ] && [ -d "$frames" ]; then
  echo "== [4/5] 帧去重 + OCR"
  python3 "$TOOLS/dedup_frames.py" "$frames"
  if [ "${FORCE:-0}" = 1 ]; then python3 "$TOOLS/ocr_frames.py" "$frames" --force; else python3 "$TOOLS/ocr_frames.py" "$frames"; fi
fi
# 课件 PDF 匹配(可选):course.json 里该单元配了 slides_dir 且目录里有 PDF 时,用课件文字给帧定页码
meta="$(COURSE_ROOT="$ROOT" python3 "$TOOLS/course_meta.py" "$video" --json 2>/dev/null || true)"
slides_dir="$(printf '%s' "$meta" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("slides_dir") or "")' 2>/dev/null || true)"
if [ "$is_video" = 1 ] && [ -n "$slides_dir" ] && ls "$ROOT/$slides_dir"/*.pdf >/dev/null 2>&1 && command -v pdftotext >/dev/null; then
  echo "== [4b] 课件 PDF 匹配 ($slides_dir)"; python3 "$TOOLS/match_slides.py" "$frames" "$ROOT/$slides_dir"
fi
echo "== [5/5] bundle + 讲义稿"; python3 "$TOOLS/build_bundle.py" "$video"
rm -f "$base.transcribe.log" "$base.frames.log"
notes="总结/<单元代码>/$name.md"
if [ -n "$meta" ]; then
  echo "== 课程信息: $(COURSE_ROOT="$ROOT" python3 "$TOOLS/course_meta.py" "$video" 2>/dev/null | head -1)"
  notes="$(printf '%s' "$meta" | python3 -c 'import sys,json; print(json.load(sys.stdin)["notes_path"])')"
fi
echo "== 全部完成,用时 $(( $(date +%s) - t0 )) 秒。下一步:读 $base.grounded.md 写总结,总结存 $notes,写完跑 工具/add_links.py 与 工具/check_summary.py"
