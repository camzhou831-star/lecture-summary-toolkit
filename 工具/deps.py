#!/usr/bin/env python3
"""外部程序与模型(视频模式用):在哪找、缺了怎么装。macOS / Windows / Linux 共用。
- find(cmd):先查 PATH;Windows 上再查常见安装位置(安装程序不一定把它们加进 PATH,或者加了但当前终端还没刷新)
- install_whisper_windows():下载官方预编译的 whisper.cpp(CPU 版),校验 SHA-256 后解压到工具数据目录
- ensure_model(name) / ensure_vad():下载 whisper 模型与 Silero VAD 模型(先写 .tmp,完成后再改名)
- short_path(p):Windows 上把含中文的路径换成 8.3 短路径,whisper.cpp 按系统代码页读文件名,中文路径会打不开
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, zipfile
WINDOWS = sys.platform == "win32"
DATA = os.environ.get("LSK_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "lecture-summary-toolkit")
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "whisper-models")
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
VAD_NAME = "ggml-silero-v5.1.2.bin"
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/" + VAD_NAME
# Windows 版 whisper.cpp,都是 b5130(= v1.9.4,2026-09-11);换版本时同时改文件名 / URL 和哈希
#   vulkan:GPU 版,NVIDIA / AMD / Intel(含核显)通用;官方不发 Windows Vulkan 包,由本仓库 .github/workflows/whisper-vulkan.yml 编译,
#           固定存档在本仓库 Release whisper-vulkan-b5130(私有),随 Windows 安装包放在 vendor/ 下(不联网);lsk setup 默认装它
#   cuda  :NVIDIA 专用的官方包(约 675 MB,自带 CUDA 运行库),lsk setup --cuda 才装;RTX 50 系是否支持未验证
#   cpu   :官方纯 CPU 包(约 8 MB);GPU 版装好后也会装它,GPU 版启动不了(比如没有显卡驱动)时转写自动换它
WHISPER_TAG = "b5130"
WHISPER_REL = f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_TAG}/"
VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
WHISPER_WIN = {"vulkan": {"file": os.path.join(VENDOR, f"whisper-vulkan-{WHISPER_TAG}-x64.zip"), "size": "18 MB",
                          "sha256": "4e18f91f73c8d0a922352586138c5e7c3d357cc9b20c2b42385c2317c382963e"},
               "cuda": {"url": WHISPER_REL + "whisper-cublas-12.4.0-bin-x64.zip", "size": "675 MB",
                        "sha256": "af520ddd034d985b55dfeea3e465ed93653ba2aee1a55e865033edc548c272a7"},
               "cpu": {"url": WHISPER_REL + "whisper-bin-x64.zip", "size": "8 MB",
                       "sha256": "f9ec6c52a2e949b62ab51fa21d0d497958f9e41c3010c157c4e42932d5316f3c"}}
GPU_KINDS = ("cuda", "vulkan")                          # 都装了时优先顺序
def whisper_win_dir(kind): return os.path.join(DATA, f"whisper.cpp-{WHISPER_TAG}" + ("" if kind == "cpu" else "-" + kind))

def gpus():
    """Windows:显卡名称(WMI);拿不到返回 []。远程桌面 / 基本显示适配器这类虚拟设备不算"""
    try: r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                            capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError): return []
    skip = ("basic display", "basic render", "remote", "hyper-v", "virtual", "parsec", "citrix")
    return [l.strip() for l in r.stdout.splitlines() if l.strip() and not any(k in l.lower() for k in skip)]

def probe_whisper(cli, model, wav=None, args=(), env=None):
    """试跑 whisper-cli(默认 1 秒静音),看它实际用的是哪个后端。返回 (能跑, 后端名或 None, 显卡名或 None, 转写文字, 出错时的最后几行)"""
    import wave
    with tempfile.TemporaryDirectory() as d:
        if not wav:
            wav = os.path.join(d, "silence.wav")
            with wave.open(wav, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0" * 32000)
        try: r = subprocess.run([cli, "-m", short_path(model), "-f", short_path(wav), "-l", "en", *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=900, env=dict(os.environ, **(env or {})))
        except (OSError, subprocess.SubprocessError) as e: return False, None, None, "", str(e)
    log = r.stdout + r.stderr
    backend = re.search(r"whisper_backend_init_gpu: using (\S+) backend", log)
    name = re.search(r"ggml_vulkan: \d+ = (.+?) \(|Device \d+: ([^,]+),|GPU name:\s+\S+ \((.+?)\)", log)
    text = " ".join(m[1] for m in re.finditer(r"^\[[\d:.]+ --> [\d:.]+\]\s*(.*)$", r.stdout, re.M))
    return r.returncode == 0, backend and backend[1], name and next(g for g in name.groups() if g), text, "\n".join(log.strip().splitlines()[-5:])

# ---------- Windows GPU 自检 ----------
# 各家显卡驱动对 Vulkan 的支持参差不齐(CI 上 Mesa lavapipe 在 flash attention + 矩阵加速(coopmat)组合下输出乱码),
# 所以 lsk setup 用示例视频的一段已知旁白逐个试下面的设置,取第一个转写正确的,存进 SETTINGS,transcribe.py 照着用
SETTINGS = os.path.join(DATA, "whisper-settings.json")
GPU_MODES = {"gpu":                  ([], {}),
             "gpu-no-coopmat":       ([], {"GGML_VK_DISABLE_COOPMAT": "1"}),
             "gpu-no-fa":            (["-nfa"], {}),
             "gpu-no-coopmat-no-fa": (["-nfa"], {"GGML_VK_DISABLE_COOPMAT": "1"})}
DEMO = os.path.join(os.path.dirname(VENDOR), "examples", "demo", "课程视频", "DEMO1001 - 01 Jan 26-s1-demo")
CHECK_SECONDS = 45

def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def mode_args(settings=None):
    """transcribe.py 用:按自检结果给出 (whisper-cli 路径或 None, 额外参数, 额外环境变量)。None 表示照常(用 find 找到的)"""
    st = load_settings() if settings is None else settings
    m = st.get("mode")
    if m == "cpu": return os.path.join(whisper_win_dir("cpu"), "whisper-cli.exe"), ["--no-gpu"], {}
    args, env = GPU_MODES.get(m, ([], {}))
    return None, list(args), dict(env)

def _words(t): return re.findall(r"[a-z']+", t.lower())

def check_text(text, reference):
    """自检通过:参考旁白的词有 80% 以上出现在转写里,并且转写带句末标点(防整篇无标点)"""
    ref, got = _words(reference), set(_words(text))
    return bool(ref) and sum(w in got for w in ref) / len(ref) >= 0.8 and bool(re.search(r"[.?!]", text))

def calibrate(model, log=print):
    """Windows:逐个试 GPU 设置,都不行就用 CPU 版;结果写进 SETTINGS 并返回。没有示例视频或 ffmpeg 时返回 None"""
    srt, mp4 = DEMO + ".srt", DEMO + ".mp4"
    if not (os.path.isfile(srt) and os.path.isfile(mp4) and find("ffmpeg")): return None
    ref = []
    for m in re.finditer(r"(\d+):(\d+):(\d+),\d+ --> (\d+):(\d+):(\d+),\d+\s*\n(.+?)(?:\n\n|\Z)", open(srt, encoding="utf-8").read(), re.S):
        if int(m[4]) * 3600 + int(m[5]) * 60 + int(m[6]) <= CHECK_SECONDS: ref.append(m[7])
    reference = " ".join(ref)
    prompt = ["--prompt", "Welcome back, everyone. Today we will continue with the lecture."]   # 与 transcribe 的英文开头句一致
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "check.wav")
        if subprocess.run([exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", mp4, "-t", str(CHECK_SECONDS),
                           "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav]).returncode != 0: return None
        tried = []
        gpu_cli = next((os.path.join(whisper_win_dir(k), "whisper-cli.exe") for k in GPU_KINDS
                        if os.path.isfile(os.path.join(whisper_win_dir(k), "whisper-cli.exe"))), None)
        if gpu_cli:
            for mode, (args, env) in GPU_MODES.items():
                ok, backend, gpu, text, tail = probe_whisper(gpu_cli, model, wav, [*args, *prompt], env)
                good = ok and backend and check_text(text, reference)
                log(f"   {'✅' if good else '❌'} {mode}: " + (f"{gpu or backend}  " if backend else "没用上显卡 / no GPU  " if ok else "启动失败 / failed  ")
                    + (text[:70] if ok else tail.splitlines()[-1] if tail else ""))
                tried.append(mode)
                if good: return _save({"mode": mode, "build": whisper_win_kind(gpu_cli), "gpu": gpu or backend, "tried": tried})
                if ok and not backend: break                  # 根本没找到显卡,其它 GPU 设置也不会有用
        cpu_cli = os.path.join(whisper_win_dir("cpu"), "whisper-cli.exe")
        ok, _, _, text, tail = probe_whisper(cpu_cli, model, wav, ["--no-gpu", *prompt])
        log(f"   {'✅' if ok and check_text(text, reference) else '❌'} cpu: " + (text[:70] if ok else tail))
        return _save({"mode": "cpu", "build": "cpu", "gpu": None, "tried": tried + ["cpu"]})

def _save(st):
    os.makedirs(DATA, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False, indent=2)
    return st

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
            "whisper-cli": [*map(whisper_win_dir, GPU_KINDS), whisper_win_dir("cpu")],   # 装了 GPU 版就优先用
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

# winget 连不上(代理 / 地区限制,如 0x80072efd)时的手动安装包;装到默认位置 find() 就找得到
TESSERACT_WIN_URL = "https://github.com/UB-Mannheim/tesseract/releases"
# 缺了怎么装:(macOS, Windows, Linux)
INSTALL = {"ffmpeg": ("brew install ffmpeg", "winget install Gyan.FFmpeg", "sudo apt-get install ffmpeg"),
           "whisper-cli": ("brew install whisper-cpp", "lsk setup", "build from https://github.com/ggml-org/whisper.cpp and put whisper-cli on PATH"),
           "tesseract": ("brew install tesseract", "winget install UB-Mannheim.TesseractOCR  (winget 失败就下载安装包 / if winget fails: " + TESSERACT_WIN_URL + ")", "sudo apt-get install tesseract-ocr"),
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
    """解压 Windows 版 whisper.cpp(kind: vulkan / cuda / cpu;vulkan 用安装包 vendor/ 里的 zip,另两种从官方下载);
    已装好直接返回 whisper-cli.exe 路径。都先校验 SHA-256"""
    pkg, dest = WHISPER_WIN[kind], whisper_win_dir(kind)
    cli = os.path.join(dest, "whisper-cli.exe")
    if os.path.isfile(cli): return cli
    with tempfile.TemporaryDirectory() as d:
        if "file" in pkg:
            z = os.environ.get("LSK_WHISPER_VULKAN_ZIP") or pkg["file"]
            if not os.path.isfile(z): sys.exit(f"错误: 找不到 {pkg['file']}(Windows 安装包自带;从源码运行时请先下载 whisper-vulkan 编译产物)")
            if sha256_of(z) != pkg["sha256"]: sys.exit(f"错误: {z} 校验失败(SHA-256 不符),请重新下载安装包")
        else:
            z = download(pkg["url"], os.path.join(d, "whisper.zip"), pkg["sha256"], f"whisper.cpp {WHISPER_TAG} {kind}(约 {pkg['size']})")
        tmpdir = dest + ".tmp"
        shutil.rmtree(tmpdir, ignore_errors=True); os.makedirs(tmpdir)
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():                        # 官方包的文件在 Release/ 下,平铺解压
                n = os.path.basename(m.filename)
                if not n or m.is_dir(): continue
                with zf.open(m) as src, open(os.path.join(tmpdir, n), "wb") as dst: shutil.copyfileobj(src, dst)
        if not os.path.isfile(os.path.join(tmpdir, "whisper-cli.exe")): sys.exit("错误: whisper.cpp 包里没有 whisper-cli.exe")
        shutil.rmtree(dest, ignore_errors=True); os.replace(tmpdir, dest)
    print(f"== whisper.cpp ({kind}) 已装到 {dest}", file=sys.stderr)
    return cli

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def short_path(p):
    """Windows:已存在的路径换成 8.3 短路径(全 ASCII);拿不到就原样返回。其它系统原样返回"""
    if not WINDOWS or p.isascii(): return p
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, len(buf))
    return buf.value if n and buf.value.isascii() else p
