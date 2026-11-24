#!/usr/bin/env bash
# 总结工作台一键安装 + 启动(macOS;Linux 尽量帮你装,装不了的会说怎么办)
# One-command setup + launch for the Lecture Workbench (macOS; best effort on Linux)
#
#   bash setup.sh            装好缺的工具,然后启动并打开浏览器 / install what's missing, start, open the browser
#   bash setup.sh --no-start 只装不启动 / install only
#
# 只装缺的,已经有的跳过;可以放心重复运行。不会替你登录任何账号,也不会改你的 API Key。
set -euo pipefail
cd "$(dirname "$0")"
START=1; [ "${1:-}" = "--no-start" ] && START=0
# 中文还是英文:看 LANG / LC_ALL,Mac 上再看系统首选语言
SYS_LANG="${LC_ALL:-}${LANG:-}$( [ "$(uname -s)" = Darwin ] && defaults read -g AppleLanguages 2>/dev/null | sed -n 2p )"
zh() { case "$SYS_LANG" in *zh*) return 0;; *) return 1;; esac; }
say() { if zh; then echo "$1"; else echo "$2"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

say "== 总结工作台:检查和安装" "== Lecture Workbench: checking and installing"
OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
  if ! have brew; then
    say "需要先装 Homebrew(Mac 上装软件用)。在终端运行下面这一行,按提示输入开机密码,装完再运行一次本脚本:" \
        "Homebrew is needed first (it installs software on a Mac). Run this line, enter your Mac password when asked, then run this script again:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
  fi
  for pkg in uv yt-dlp ffmpeg whisper-cpp; do
    if brew list --formula "$pkg" >/dev/null 2>&1; then say "   ✓ $pkg 已安装" "   ✓ $pkg installed"
    else say "   … 安装 $pkg" "   … installing $pkg"; brew install "$pkg"; fi
  done
elif [ "$OS" = "Linux" ]; then
  have ffmpeg || { say "   … 安装 ffmpeg(要 sudo 密码)" "   … installing ffmpeg (needs sudo)"; sudo apt-get install -y ffmpeg || true; }
  have uv || { say "   … 安装 uv" "   … installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
  have yt-dlp || { say "   … 安装 yt-dlp" "   … installing yt-dlp"; uv tool install yt-dlp; }
  have whisper-cli || say "   ! whisper-cli 要自己编译:https://github.com/ggml-org/whisper.cpp(只用网站字幕的话可以先不装)" \
                          "   ! Build whisper-cli yourself: https://github.com/ggml-org/whisper.cpp (not needed if sites have subtitles)"
else
  say "这个脚本支持 macOS 和 Linux。Windows 请在 WSL 里运行。" "This script supports macOS and Linux. On Windows, run it inside WSL."
  exit 1
fi

say "== Python 依赖" "== Python dependencies"
uv sync --quiet

say "== 写总结的 AI(三选一)" "== AI for summaries (you need one)"
AI=0
if have claude; then say "   ✓ Claude Code(没登录过的话,运行一次 claude 登录)" "   ✓ Claude Code (run claude once to sign in if you haven't)"; AI=1; fi
if have codex; then say "   ✓ Codex(没登录过的话,运行一次 codex 登录)" "   ✓ Codex (run codex once to sign in if you haven't)"; AI=1; fi
if [ -f "${WORKBENCH_CONFIG:-$HOME/.config/lecture-workbench/config.json}" ] || [ -n "${DEEPSEEK_API_KEY:-}${LLM_API_KEY:-}" ]; then
  say "   ✓ 已有 API 配置" "   ✓ API configuration found"; AI=1
fi
if [ "$AI" = 0 ]; then
  say "   还没有。有会员的话不用 API Key,装一个就行:" "   None yet. With a paid plan you don't need an API key — install one:"
  say "     Claude Pro / Max:   npm i -g @anthropic-ai/claude-code && claude" "     Claude Pro / Max:   npm i -g @anthropic-ai/claude-code && claude"
  say "     ChatGPT Plus / Pro: npm i -g @openai/codex && codex" "     ChatGPT Plus / Pro: npm i -g @openai/codex && codex"
  have npm || say "     (没有 npm 的话先 brew install node)" "     (no npm? run brew install node first)"
  say "   工作台照样能打开,首页会提示你。" "   The workbench still opens; its home page will remind you."
fi

[ "$START" = 1 ] || { say "== 装好了。启动:cd \"$(pwd)\" && uv run python -m wb" "== Done. Start with: cd \"$(pwd)\" && uv run python -m wb"; exit 0; }

PORT="${PORT:-8770}"
URL="http://127.0.0.1:$PORT"
if curl -s -o /dev/null "$URL/api/config" 2>/dev/null; then
  say "== 工作台已经在运行:$URL" "== The workbench is already running: $URL"
  have open && open "$URL" || true
  exit 0
fi
say "== 启动工作台:$URL(关掉这个终端窗口或按 Ctrl+C 就会停)" "== Starting the workbench at $URL (close this window or press Ctrl+C to stop)"
( sleep 2; if have open; then open "$URL"; elif have xdg-open; then xdg-open "$URL"; fi ) >/dev/null 2>&1 &
exec uv run python -m wb
