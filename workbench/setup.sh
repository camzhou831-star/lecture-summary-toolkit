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

brew_env() {   # 装了 Homebrew 但这个窗口的 PATH 里还没有(双击启动、刚装完)时,补上
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && { eval "$("$b" shellenv)"; return 0; }
  done
  return 1
}
BREW_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"

# 中国大陆连不上 GitHub 的 raw 地址时(或 WORKBENCH_CN=1),Homebrew、Python、Python 包都换国内镜像:
# Homebrew 用中科大镜像(https://mirrors.ustc.edu.cn/help/brew.git.html),Python 用 npmmirror,Python 包用阿里云
CN=0
if [ "${WORKBENCH_CN:-}" = 1 ]; then CN=1
elif [ "${WORKBENCH_CN:-}" != 0 ] && ! curl -fsI --max-time 8 https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh >/dev/null 2>&1; then CN=1; fi
if [ "$CN" = 1 ]; then
  say "== 连不上 GitHub,改用国内镜像下载(中科大 Homebrew、npmmirror、阿里云 PyPI)" \
      "== GitHub is unreachable; using mirrors in mainland China (USTC Homebrew, npmmirror, Aliyun PyPI)"
  export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
  export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
  export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
  export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
  export HOMEBREW_NO_AUTO_UPDATE=1
  export UV_PYTHON_INSTALL_MIRROR="https://registry.npmmirror.com/-/binary/python-build-standalone"
  export UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple/"
  export HF_ENDPOINT="https://hf-mirror.com"
  BREW_URL="https://mirrors.ustc.edu.cn/misc/brew-install.sh"
fi

if [ "$OS" = "Darwin" ]; then
  have brew || brew_env || true
  if ! have brew; then
    say "需要先装 Homebrew(Mac 上装软件用的官方工具,https://brew.sh)。" "Homebrew is needed first (the standard way to install software on a Mac, https://brew.sh)."
    if [ -t 0 ]; then
      if zh; then read -r -p "现在安装吗?过程中要输入一次开机密码 [y/N] " ans; else read -r -p "Install it now? You'll be asked for your Mac password once [y/N] " ans; fi
      case "$ans" in
        y|Y|yes|YES) /bin/bash -c "$(curl -fsSL "$BREW_URL")" && brew_env || true ;;
      esac
    fi
    if ! have brew; then
      say "没有装上。可以在终端运行下面这一行装好,再重新运行本脚本(或再双击「启动工作台」):" \
          "Not installed. Run this line in Terminal, then run this script again (or double-click Start again):"
      [ "$CN" = 1 ] && echo "  export HOMEBREW_BREW_GIT_REMOTE=$HOMEBREW_BREW_GIT_REMOTE HOMEBREW_CORE_GIT_REMOTE=$HOMEBREW_CORE_GIT_REMOTE HOMEBREW_BOTTLE_DOMAIN=$HOMEBREW_BOTTLE_DOMAIN HOMEBREW_API_DOMAIN=$HOMEBREW_API_DOMAIN"
      echo "  /bin/bash -c \"\$(curl -fsSL $BREW_URL)\""
      exit 1
    fi
  fi
  for pkg in uv yt-dlp ffmpeg whisper-cpp tesseract poppler; do    # tesseract / poppler:读视频画面文字、读课件 PDF(课程总结用)
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

# 语音模型(约 1.5 GB)安装时就下好,不然第一次总结会在「拿文字稿」那一步卡好几分钟。已经有就跳过
if [ "$OS" = "Darwin" ] || have whisper-cli; then
  say "== 语音模型(约 1.5 GB,只下载这一次,已经有就跳过)" "== Speech model (about 1.5 GB, downloaded once; skipped if present)"
  uv run python -c "import sys; sys.path.insert(0, '../工具'); import deps, os; deps.ensure_model(os.environ.get('WHISPER_MODEL', 'large-v3-turbo')); deps.ensure_vad()" \
    && say "   ✓ 语音模型已就绪" "   ✓ Speech model ready" \
    || say "   ! 模型没下载成功(多半是网络),不影响打开工作台;第一次转写时会再下载" "   ! Model download failed (usually the network); the workbench still opens and will retry on the first transcription"
fi

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
