#!/usr/bin/env python3
"""外部程序与模型(视频模式用):在哪找、缺了怎么装。macOS / Windows / Linux 共用。
- find(cmd):先查 PATH;Windows 上再查常见安装位置(安装程序不一定把它们加进 PATH,或者加了但当前终端还没刷新)
- install_whisper_windows():下载官方预编译的 whisper.cpp(CPU 版),校验 SHA-256 后解压到工具数据目录
- ensure_model(name) / ensure_vad():下载 whisper 模型与 Silero VAD 模型(先写 .tmp,完成后再改名)
- short_path(p):Windows 上把含中文的路径换成 8.3 短路径,whisper.cpp 按系统代码页读文件名,中文路径会打不开
"""
import hashlib, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile
WINDOWS = sys.platform == "win32"
DATA = os.environ.get("LSK_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "lecture-summary-toolkit")
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "whisper-models")
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
VAD_NAME = "ggml-silero-v5.1.2.bin"
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/" + VAD_NAME
# Windows 版 whisper.cpp:官方 release b5130(= v1.9.4,2026-09-11)的预编译包;换版本时同时改 URL 和哈希
#   cpu :纯 CPU(约 8 MB)
#   cuda:NVIDIA 显卡用(约 675 MB,自带 cuBLAS / cudart / nvrtc 运行库,只需要显卡驱动);检测到 NVIDIA 显卡时 lsk setup 自动选它
WHISPER_TAG = "b5130"
WHISPER_REL = f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_TAG}/"
WHISPER_WIN = {"cpu": {"url": WHISPER_REL + "whisper-bin-x64.zip", "size": "8 MB",
                       "sha256": "f9ec6c52a2e949b62ab51fa21d0d497958f9e41c3010c157c4e42932d5316f3c"},
               "cuda": {"url": WHISPER_REL + "whisper-cublas-12.4.0-bin-x64.zip", "size": "675 MB",
                        "sha256": "af520ddd034d985b55dfeea3e465ed93653ba2aee1a55e865033edc548c272a7"}}
def whisper_win_dir(kind): return os.path.join(DATA, f"whisper.cpp-{WHISPER_TAG}" + ("" if kind == "cpu" else "-" + kind))

def nvidia_gpu():
    """Windows:有 NVIDIA 显卡和驱动时返回显卡名(nvidia-smi 随驱动安装),否则 None"""
    smi = shutil.which("nvidia-smi") or os.path.expandvars(r"%SystemRoot%\System32\nvidia-smi.exe")
    if not os.path.isfile(smi): return None
    try: r = subprocess.run([smi, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError): return None
    name = r.stdout.strip().splitlines()[0].strip() if r.returncode == 0 and r.stdout.strip() else None
    return name

def whisper_win_kind(path):
    """whisper-cli.exe 属于哪个包(cpu / cuda);不是我们装的返回 None"""
    for kind in WHISPER_WIN:
        if path and os.path.normcase(os.path.dirname(path)) == os.path.normcase(whisper_win_dir(kind)): return kind
    return None

def _win_dirs(cmd):
    """Windows 上 PATH 之外常见的安装位置"""
    e = os.path.expandvars
    links = e(r"%LOCALAPPDATA%\Microsoft\WinGet\Links")                    # winget 装的命令行程序(新开终端前不在 PATH 里)
    return {"ffmpeg": [links, e(r"%ProgramData%\chocolatey\bin")],
            "ffprobe": [links, e(r"%ProgramData%\chocolatey\bin")],
            "tesseract": [e(r"%ProgramFiles%\Tesseract-OCR"), e(r"%LOCALAPPDATA%\Programs\Tesseract-OCR"), e(r"%ProgramFiles(x86)%\Tesseract-OCR")],
            "whisper-cli": [whisper_win_dir("cuda"), whisper_win_dir("cpu")],   # 装了 GPU 版就优先用
            "pdftotext": [links], "yt-dlp": [links]}.get(cmd, [])

def find(cmd):
    p = shutil.which(cmd)
    if p or not WINDOWS: return p
    for d in _win_dirs(cmd):
        exe = os.path.join(d, cmd + ".exe")
        if os.path.isfile(exe): return exe
    return None

def exe(cmd):
    """给 subprocess 用:找得到就用完整路径,找不到原样返回命令名(让调用方按原来的方式报错)"""
    return find(cmd) or cmd

# 缺了怎么装:(macOS, Windows, Linux)
INSTALL = {"ffmpeg": ("brew install ffmpeg", "winget install Gyan.FFmpeg", "sudo apt-get install ffmpeg"),
           "whisper-cli": ("brew install whisper-cpp", "lsk setup", "build from https://github.com/ggml-org/whisper.cpp and put whisper-cli on PATH"),
           "tesseract": ("brew install tesseract", "winget install UB-Mannheim.TesseractOCR", "sudo apt-get install tesseract-ocr"),
           "poppler": ("brew install poppler", "py -m pip install pypdf", "sudo apt-get install poppler-utils"),
           "pillow": ("pip3 install pillow", "py -m pip install pillow", "pip3 install pillow")}
def how(pkg):
    mac, win, linux = INSTALL[pkg]
    if WINDOWS: return win
    return mac if sys.platform == "darwin" or shutil.which("brew") else linux

def download(url, dest, sha256=None, label=None):
    """下载到 dest(先写 dest.tmp,校验通过再改名);每 10% 打印一次进度到 stderr"""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp, h, done, shown = dest + ".tmp", hashlib.sha256(), 0, -1
    print(f"== 下载 {label or os.path.basename(dest)}: {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(1 << 20)
            if not chunk: break
            f.write(chunk); h.update(chunk); done += len(chunk)
            if total and done * 10 // total != shown:
                shown = done * 10 // total; print(f"   {shown * 10}%  ({done >> 20} / {total >> 20} MB)", file=sys.stderr)
    if sha256 and h.hexdigest() != sha256:
        os.remove(tmp); sys.exit(f"错误: {os.path.basename(dest)} 校验失败(SHA-256 不符),已删除;请重试")
    os.replace(tmp, dest)
    return dest

def ensure_model(name):
    path = os.path.join(MODEL_DIR, f"ggml-{name}.bin")
    if not os.path.isfile(path):
        print(f"首次使用,下载 whisper 模型 {name} ...", file=sys.stderr)
        download(MODEL_URL.format(name=name), path)
    return path

def ensure_vad():
    path = os.path.join(MODEL_DIR, VAD_NAME)
    if not os.path.isfile(path):
        print("首次使用,下载 Silero VAD 模型(约 1 MB)...", file=sys.stderr)
        download(VAD_URL, path)
    return path

def install_whisper_windows(kind="cpu"):
    """下载并解压 Windows 版 whisper.cpp(kind: cpu / cuda);已装好直接返回 whisper-cli.exe 路径"""
    pkg, dest = WHISPER_WIN[kind], whisper_win_dir(kind)
    cli = os.path.join(dest, "whisper-cli.exe")
    if os.path.isfile(cli): return cli
    with tempfile.TemporaryDirectory() as d:
        z = download(pkg["url"], os.path.join(d, "whisper.zip"), pkg["sha256"], f"whisper.cpp {WHISPER_TAG} {kind}(约 {pkg['size']})")
        tmpdir = dest + ".tmp"
        shutil.rmtree(tmpdir, ignore_errors=True); os.makedirs(tmpdir)
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():                        # 包里文件都在 Release/ 下,平铺解压
                n = os.path.basename(m.filename)
                if not n or m.is_dir(): continue
                with zf.open(m) as src, open(os.path.join(tmpdir, n), "wb") as dst: shutil.copyfileobj(src, dst)
        if not os.path.isfile(os.path.join(tmpdir, "whisper-cli.exe")): sys.exit("错误: 下载的 whisper.cpp 包里没有 whisper-cli.exe")
        shutil.rmtree(dest, ignore_errors=True); os.replace(tmpdir, dest)
    print(f"== whisper.cpp ({kind}) 已装到 {dest}", file=sys.stderr)
    return cli

def short_path(p):
    """Windows:已存在的路径换成 8.3 短路径(全 ASCII);拿不到就原样返回。其它系统原样返回"""
    if not WINDOWS or p.isascii(): return p
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, len(buf))
    return buf.value if n and buf.value.isascii() else p
