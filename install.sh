#!/usr/bin/env bash
# 一键安装(macOS):依赖 + 模型 + 把技能装到 Claude Code 与 Codex CLI
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
echo "== 1/3 依赖(ffmpeg whisper-cpp tesseract)"
if command -v brew >/dev/null; then
  for pkg in ffmpeg whisper-cpp tesseract; do
    if brew list --formula "$pkg" >/dev/null 2>&1; then echo "   $pkg 已安装"; else brew install "$pkg"; fi
  done
elif command -v apt-get >/dev/null; then
  echo "   Linux:apt 安装 ffmpeg 与 tesseract;whisper-cpp 需自行编译(https://github.com/ggml-org/whisper.cpp)并把 whisper-cli 放进 PATH"
  sudo apt-get install -y ffmpeg tesseract-ocr
else
  echo "需要 Homebrew(macOS)或 apt(Linux);Windows 请用 WSL" >&2; exit 1
fi
python3 -c "import PIL" 2>/dev/null || pip3 install --user pillow
echo "== 2/3 模型(whisper large-v3-turbo ≈1.6GB + Silero VAD ≈1MB,首次转写时也会自动下载)"
mkdir -p "$HOME/.local/share/whisper-models"
[ -f "$HOME/.local/share/whisper-models/ggml-large-v3-turbo.bin" ] && echo "   whisper 模型已存在" || echo "   首次运行 transcribe.sh 时自动下载"
echo "== 3/3 技能 → Claude Code 与 Codex CLI(符号链接,更新仓库即同步;仓库移动后重跑本脚本)"
# Codex 新版文档的用户技能目录是 ~/.agents/skills,旧版是 ~/.codex/skills,两个都链
for dir in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills"; do
  mkdir -p "$dir"
  if [ -e "$dir/video-summary" ] && [ ! -L "$dir/video-summary" ]; then
    echo "   $dir/video-summary 已存在且不是链接,跳过(如需替换请先手动删除)"
  else
    ln -sfn "$root/skills/video-summary" "$dir/video-summary"; echo "   $dir/video-summary -> $root/skills/video-summary"
  fi
done
echo "== 完成。检查环境:bash $root/lsk doctor --video;然后在 Claude Code / Codex / Gemini CLI 里打开 $root,说:总结 <字幕或视频文件路径>"
