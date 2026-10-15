#!/usr/bin/env bash
# 一键预处理一节录播:转写(VAD+术语表)‖抓帧 → compact → 帧去重 → OCR → bundle/讲义稿
# 用法: prepare.sh <视频文件名或路径> [语言码,默认 en] 
#   文件名不带路径时依次在 课程视频/ 和 ~/Downloads/ 找;在 Downloads 找到会先移入 课程视频/
#   工作目录 = COURSE_ROOT,未设置时为本脚本所在 工具/ 的上级目录
#   环境变量: FORCE=1 忽略已有产物全部重做;FRAME_MODE=12s 抓帧模式(默认 12s);NO_VAD=1 / GLOSSARY=<文件> 透传给 transcribe.sh
#   双路录像(UWA LMS 常见:<名>.mp4 是讲台电脑屏幕,<名>-2.mp4 是实物投影仪/摄像头):自动识别同目录的 <名>-2.<ext>(或 CAM=<路径> 指定);
#     声音取两路里更响的那一路(有的课屏幕那路是静音的),产物仍归主文件名;实物投影那路用 cam_frames.py 挑手写页进 画面/<名>/cam/
#   跳过规则: 只有"转写"和"抓帧"两步在已有产物时跳过;compact、OCR(增量)、课件匹配、bundle 每次都重跑(都只要几秒)
#   帧去重只在本次真的抓了帧之后跑一次:dedup_frames 不是幂等的(删掉中间帧后前后两帧会落进同一窗口再被合并),重跑会把总结已引用的截图删掉
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
base="${video%.*}"; name="$(basename "$base")"; ext="${video##*.}"
# 第二路(实物投影/摄像头)
cam="${CAM:-}"
if [ -z "$cam" ]; then
  for cand in "$base-2.$ext" "$HOME/Downloads/$name-2.$ext"; do [ -f "$cand" ] && { cam="$cand"; break; }; done
fi
if [ -n "$cam" ] && [ ! -f "$cam" ]; then echo "错误: CAM 指定的文件不存在: $cam" >&2; exit 1; fi
if [ -n "$cam" ]; then
  case "$cam" in "$ROOT/课程视频/"*) ;; *)
    [ -e "$ROOT/课程视频/$(basename "$cam")" ] && { echo "错误: 课程视频/ 已有同名文件 $(basename "$cam")" >&2; exit 1; }
    echo "== 第二路录像不在 课程视频/,一并移入"; mv -n "$cam" "$ROOT/课程视频/"; cam="$ROOT/课程视频/$(basename "$cam")";; esac
  echo "== 双路录像: 屏幕=$(basename "$video")  实物投影=$(basename "$cam")"
fi
frames="$ROOT/画面/$name"
fresh_frames=0
is_video=1; ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$video" | grep -q video || is_video=0
t0=$(date +%s)
echo "== 预处理: $name (语言 $lang, 抓帧模式 $mode, 有画面: $is_video)"

# 响度取样:在 20%/50%/80% 三处各测 4 分钟的 mean_volume,取中位数(只测开头会被试麦/开场前的空档误导)
mean_db() {
  local f="$1" dur v vals=()
  dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | cut -d. -f1)"; dur="${dur:-0}"
  for frac in 20 50 80; do
    v="$(ffmpeg -v info -ss $(( dur * frac / 100 )) -t 240 -vn -sn -dn -i "$f" -af volumedetect -f null - 2>&1 | grep -oE "mean_volume: [-0-9.]+" | grep -oE "[-0-9.]+" || echo "-99")"
    vals+=("$v")
  done
  printf '%s\n' "${vals[@]}" | sort -n | sed -n 2p
}
audio_src="$video"
if [ -n "$cam" ]; then
  d1="$(mean_db "$video")"; d2="$(mean_db "$cam")"
  if python3 -c "import sys; sys.exit(0 if float('$d2') > float('$d1') + 6 else 1)"; then audio_src="$cam"; fi
  echo "== 声音: 屏幕路 ${d1} dB,实物投影路 ${d2} dB(20%/50%/80% 处各 4 分钟的中位数)→ 用 $(basename "$audio_src") 转写"
fi
pids=()
if [ "${FORCE:-0}" = 1 ] || [ ! -s "$base.srt" ]; then
  echo "== [1/5] 转写 (后台)"; COURSE_ROOT="$ROOT" OUT_BASE="$base" bash "$TOOLS/transcribe.sh" "$audio_src" "$lang" > "$base.transcribe.log" 2>&1 & pids+=($!)
else echo "== [1/5] 转写: 已有 $name.srt,跳过(FORCE=1 可重做)"; fi
if [ "$is_video" = 1 ]; then
  if [ "${FORCE:-0}" = 1 ] || [ -z "$(ls "$frames" 2>/dev/null | grep -c '\.jpg$' || true)" ] || [ "$(ls "$frames" 2>/dev/null | grep -c '\.jpg$')" = 0 ]; then
    echo "== [2/5] 抓帧 (后台)"; bash "$TOOLS/extract_frames.sh" "$video" "$mode" "$frames" > "$base.frames.log" 2>&1 & pids+=($!); fresh_frames=1
  else echo "== [2/5] 抓帧: 画面/$name 已有帧,跳过(FORCE=1 可重做)"; fi
  if [ -n "$cam" ]; then
    if [ "${FORCE:-0}" = 1 ] || [ ! -s "$frames/cam/cam.json" ]; then
      echo "== [2b] 实物投影手写帧 (后台)"; python3 "$TOOLS/cam_frames.py" "$cam" "$frames/cam" > "$base.cam.log" 2>&1 & pids+=($!)
    else echo "== [2b] 手写帧: 画面/$name/cam 已有,跳过(FORCE=1 可重做)"; fi
  fi
fi
fail=0
for p in ${pids[@]+"${pids[@]}"}; do wait "$p" || fail=1; done
if [ "$fail" = 1 ]; then echo "错误: 转写或抓帧失败,看 $base.transcribe.log / $base.frames.log / $base.cam.log" >&2; exit 1; fi
tail -n 2 "$base.transcribe.log" 2>/dev/null | sed 's/^/   /' || true
tail -n 1 "$base.frames.log" 2>/dev/null | sed 's/^/   /' || true
tail -n 1 "$base.cam.log" 2>/dev/null | sed 's/^/   /' || true

echo "== [3/5] compact"; bash "$TOOLS/compact.sh" "$base.srt"
if [ "$is_video" = 1 ] && [ -d "$frames" ]; then
  echo "== [4/5] 帧去重 + OCR"
  if [ "$fresh_frames" = 1 ]; then python3 "$TOOLS/dedup_frames.py" "$frames"; else echo "   去重: 本次未重新抓帧,跳过(去重不幂等,重跑会删掉已引用的帧)"; fi
  if [ "${FORCE:-0}" = 1 ]; then python3 "$TOOLS/ocr_frames.py" "$frames" --force; else python3 "$TOOLS/ocr_frames.py" "$frames"; fi
fi
# 课件 PDF 匹配(可选):course.json 里该单元配了 slides_dir 且目录里有 PDF 时,用课件文字给帧定页码
meta="$(COURSE_ROOT="$ROOT" python3 "$TOOLS/course_meta.py" "$video" --json 2>/dev/null || true)"
slides_dir="$(printf '%s' "$meta" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("slides_dir") or "")' 2>/dev/null || true)"
if [ "$is_video" = 1 ] && [ -n "$slides_dir" ]; then
  if ! command -v pdftotext >/dev/null; then
    echo "   ⚠️ course.json 配了课件目录 $slides_dir,但没装 poppler(brew install poppler),跳过课件匹配" >&2; python3 "$TOOLS/match_slides.py" "$frames" --clear >/dev/null
  elif ! ls "$ROOT/$slides_dir"/*.pdf >/dev/null 2>&1; then
    echo "   ⚠️ course.json 配了课件目录 $slides_dir,但里面没有 PDF,跳过课件匹配" >&2; python3 "$TOOLS/match_slides.py" "$frames" --clear >/dev/null
  else
    echo "== [4b] 课件 PDF 匹配 ($slides_dir)"; python3 "$TOOLS/match_slides.py" "$frames" "$ROOT/$slides_dir" || echo "   ⚠️ 课件匹配失败,继续用工具栏页码" >&2
  fi
elif [ "$is_video" = 1 ] && [ -f "$frames/ocr.json" ]; then
  python3 "$TOOLS/match_slides.py" "$frames" --clear >/dev/null 2>&1 || true    # 没配课件:清掉以前的匹配结果,避免陈旧引用
fi
echo "== [5/5] bundle + 讲义稿"; python3 "$TOOLS/build_bundle.py" "$video"
rm -f "$base.transcribe.log" "$base.frames.log" "$base.cam.log"
notes="总结/<单元代码>/$name.md"
if [ -n "$meta" ]; then
  echo "== 课程信息: $(COURSE_ROOT="$ROOT" python3 "$TOOLS/course_meta.py" "$video" 2>/dev/null | head -1)"
  notes="$(printf '%s' "$meta" | python3 -c 'import sys,json; m=json.load(sys.stdin); print(m["notes_path_en"] if m.get("output_lang")=="en" else m["notes_path"])')"
fi
echo "== 全部完成,用时 $(( $(date +%s) - t0 )) 秒。下一步:读 $base.grounded.md 写总结,总结存 $notes(英文总结用 .en.md 结尾,语言优先级见 policy.md),写完跑 工具/add_links.py 与 工具/check_summary.py"
