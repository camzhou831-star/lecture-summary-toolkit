#!/usr/bin/env bash
# 用法: transcribe.sh <视频或音频文件> [语言码,默认auto]
# 输出: 与输入文件同目录的 <文件名>.srt 和 <文件名>.txt
# 环境变量: WHISPER_MODEL(默认 large-v3-turbo) WHISPER_MODEL_DIR  NO_VAD=1 关闭静音检测  GLOSSARY=<文件> 指定术语表  NO_GPU=1 强制 CPU
# 失败回退: Metal 崩溃(如在 agent 沙箱内)→ 自动用 --no-gpu 重试 → 再失败用基础参数重试
# 兼容 macOS 自带 bash 3.2:空数组用 ${ARR[@]+"${ARR[@]}"} 展开
set -euo pipefail

INPUT="$1"
LANG="${2:-auto}"
MODEL_NAME="${WHISPER_MODEL:-large-v3-turbo}"
MODEL_DIR="${WHISPER_MODEL_DIR:-$HOME/.local/share/whisper-models}"
MODEL_PATH="$MODEL_DIR/ggml-$MODEL_NAME.bin"
VAD_PATH="$MODEL_DIR/ggml-silero-v5.1.2.bin"
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$INPUT" ]; then
  echo "错误: 找不到文件 $INPUT" >&2
  exit 1
fi

mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_PATH" ]; then
  echo "首次使用,下载 whisper 模型 $MODEL_NAME ..." >&2
  curl -L --fail -o "$MODEL_PATH.tmp" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL_NAME.bin"
  mv "$MODEL_PATH.tmp" "$MODEL_PATH"
fi

# 静音检测(VAD):只把有人声的片段送给 whisper,静音段不再产生 "Thank you." 一类幻觉
VAD_ARGS=()
if [ "${NO_VAD:-0}" != "1" ]; then
  if [ ! -f "$VAD_PATH" ]; then
    echo "首次使用,下载 Silero VAD 模型(约 1 MB)..." >&2
    curl -L --fail -o "$VAD_PATH.tmp" \
      "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
    mv "$VAD_PATH.tmp" "$VAD_PATH"
  fi
  VAD_ARGS=(--vad -vm "$VAD_PATH" --vad-threshold 0.5 --vad-min-speech-duration-ms 250 --vad-speech-pad-ms 200)
fi

# 术语表:按文件名里的课程号(如 DEMO1001)自动选 工具/glossary/<课程号>.txt,喂给 whisper 的 --prompt 提高专有名词准确率
PROMPT_ARGS=()
GLOSSARY="${GLOSSARY:-}"
if [ -z "$GLOSSARY" ]; then
  COURSE="$(basename "$INPUT" | grep -oE '^[A-Z]{4}[0-9]{4}' || true)"
  [ -n "$COURSE" ] && [ -f "$TOOLS_DIR/glossary/$COURSE.txt" ] && GLOSSARY="$TOOLS_DIR/glossary/$COURSE.txt"
fi
if [ -n "$GLOSSARY" ] && [ -f "$GLOSSARY" ]; then
  echo "== 术语表: $GLOSSARY" >&2
  PROMPT_ARGS=(--prompt "$(tr '\n' ' ' < "$GLOSSARY")")
fi

BASE="${INPUT%.*}"
TMP_BASE="$(mktemp -t transcribe)"
TMP_WAV="$TMP_BASE.wav"
trap 'rm -f "$TMP_WAV" "$TMP_BASE"' EXIT

echo "== 提取音频..." >&2
ffmpeg -hide_banner -loglevel error -y -i "$INPUT" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP_WAV"

DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP_WAV")
echo "== 音频时长: ${DURATION%.*} 秒,开始转写 (模型: $MODEL_NAME, VAD: $([ ${#VAD_ARGS[@]} -gt 0 ] && echo 开 || echo 关))..." >&2

run_whisper() {
  whisper-cli -m "$MODEL_PATH" -f "$TMP_WAV" -l "$LANG" -t 8 "$@" \
    --output-srt --output-txt --output-file "$BASE" --no-prints
}
GPU_ARGS=()
[ "${NO_GPU:-0}" = "1" ] && GPU_ARGS=(--no-gpu)
rc=0; run_whisper ${GPU_ARGS[@]+"${GPU_ARGS[@]}"} ${VAD_ARGS[@]+"${VAD_ARGS[@]}"} ${PROMPT_ARGS[@]+"${PROMPT_ARGS[@]}"} --suppress-nst || rc=$?
if [ "$rc" -ne 0 ] && [ ${#GPU_ARGS[@]} -eq 0 ]; then
  # 沙箱/部分环境下 Metal 会段错误(退出码 139),改用 CPU 重试(慢 3-5 倍,但能跑)
  echo "== whisper-cli 失败(退出码 $rc),改用 CPU(--no-gpu)重试..." >&2
  rc=0; run_whisper --no-gpu ${VAD_ARGS[@]+"${VAD_ARGS[@]}"} ${PROMPT_ARGS[@]+"${PROMPT_ARGS[@]}"} --suppress-nst || rc=$?
fi
if [ "$rc" -ne 0 ]; then
  echo "== whisper-cli 仍失败(退出码 $rc),改用不带 VAD/术语表的基础参数最后重试一次..." >&2
  rc=0; run_whisper ${GPU_ARGS[@]+"${GPU_ARGS[@]}"} || rc=$?
  [ "$rc" -eq 0 ] || { echo "错误: whisper-cli 三次都失败(最后退出码 $rc),放弃" >&2; exit 1; }
fi
[ -s "$BASE.srt" ] || { echo "错误: 转写没有产出 $BASE.srt" >&2; exit 1; }

echo "== 完成:" >&2
echo "$BASE.srt"
echo "$BASE.txt"
