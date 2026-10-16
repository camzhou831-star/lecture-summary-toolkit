#!/usr/bin/env python3
"""lsk — 课程总结工具的总入口(给智能体和新手用;一次调用做完一个阶段,不用记各个脚本)
用法:
  lsk doctor [--video] [--lang zh|en]          检查环境:字幕模式要什么、视频模式还缺什么,缺的给出安装命令
  lsk setup [--cpu|--cuda]                     视频模式准备:下载 whisper 模型与 VAD 模型,试跑一次看用没用上 GPU;Windows 上还会装 whisper.cpp:
                                               默认 Vulkan GPU 版(安装包自带,NVIDIA / AMD / Intel 通用)+ CPU 兜底;--cuda NVIDIA 官方版,--cpu 只用 CPU
  lsk install [--skills-only]                  Windows 一键安装(install.cmd 调它):winget 装 ffmpeg / tesseract、pip 装 pillow / pypdf、
                                               lsk setup,再把技能链接到 Claude Code 与 Codex 的技能目录;macOS / Linux 转去跑 install.sh
  lsk run <字幕.srt|.vtt|视频> [--unit DEMO1001 --date 2026-08-26] [--slides <课件.pdf|目录>] [--lang en] [--force]
                                               字幕模式:放好字幕 → compact → 讲义稿(+ 课件逐页文字);视频模式调用 prepare.sh(Windows 上是 prepare.py;实验性)
  lsk finish <总结.md>                          写完总结后:加回跳链接 → 检查 → 重生成考点库
  lsk review <总结.md>                          准备审核包(见 skills/video-summary/review.md)
目录:COURSE_ROOT 环境变量,默认是本工具目录;字幕、讲义稿在 课程视频/,总结在 总结/<单元>/
"""
import argparse, datetime, os, re, shutil, subprocess, sys
TOOLS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, TOOLS)
import course_meta, deps, headings as H
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(TOOLS)
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav")
MODEL_DIR = deps.MODEL_DIR
WINDOWS = sys.platform == "win32"
# 子进程统一用 UTF-8(Windows 默认 GBK / cp1252),输出按 UTF-8 解码
def child_env(): return dict(os.environ, COURSE_ROOT=ROOT, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
UTF8 = {"encoding": "utf-8", "errors": "replace"}

MSG = {
    "zh": {"ok": "可用", "missing": "缺少", "optional": "可选", "sub_ready": "字幕模式:可以用(只需要 Python)。",
           "vid_ready": "视频模式:可以用。", "vid_missing": "视频模式(实验性):还缺 {n} 项,装好后再用;只有字幕的话不用装。",
           "slides_none": "读课件 PDF 需要 pdftotext(poppler)或 Python 包 pypdf,二选一;没有的话只用字幕也能总结。",
           "clients": "检测到的 AI 客户端:{c}", "no_client": "没检测到命令行版 AI 客户端(Codex / Claude Code / Gemini CLI);用桌面版也可以,打开本文件夹即可。",
           "py_old": "Python 版本太旧({v}),需要 3.9 以上", "how": "安装命令", "model_auto": "第一次处理视频时自动下载(约 1.6 GB)",
           "setup": "装好上面缺的程序后,运行 lsk setup 下载模型{w}",
           "gpu_hint": "检测到显卡 {g},但装的是 CPU 版 whisper.cpp;运行 lsk setup 换成 GPU 版(转写快很多)"},
    "en": {"ok": "ready", "missing": "missing", "optional": "optional", "sub_ready": "Subtitle mode: ready (only needs Python).",
           "vid_ready": "Video mode: ready.", "vid_missing": "Video mode (experimental): {n} item(s) missing. Not needed if you only have subtitles.",
           "slides_none": "Reading slide PDFs needs pdftotext (poppler) or the Python package pypdf; without them, subtitles alone still work.",
           "clients": "AI clients found: {c}", "no_client": "No command-line AI client found (Codex / Claude Code / Gemini CLI); a desktop app also works: open this folder in it.",
           "py_old": "Python is too old ({v}); 3.9 or newer is required", "how": "install with", "model_auto": "downloaded automatically on the first video run (about 1.6 GB)",
           "setup": "After installing the missing programs above, run lsk setup to download the models{w}",
           "gpu_hint": "GPU {g} found, but the CPU build of whisper.cpp is installed; run lsk setup to get the GPU build (much faster)"},
}

def lang_default():
    """提示语言:course.json 的 output_lang(中文包 / 英文包里已预设)优先,其次系统语言"""
    try: lg = course_meta.load_config(ROOT).get("output_lang")
    except SystemExit: lg = None
    if lg in MSG: return lg
    env = (os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")).lower()
    if not env and WINDOWS:   # Windows 一般没有 LANG,看系统区域设置(如 Chinese (Simplified)_China)
        import locale; env = (locale.getlocale()[0] or "").lower()
    return "zh" if env.startswith(("zh", "chinese")) else "en"

def have(cmd): return deps.find(cmd) is not None

def has_module(m):
    try: __import__(m); return True
    except ImportError: return False

def win_build():
    """Windows:whisper-cli 是哪个包,显示在 doctor 里"""
    kind = deps.whisper_win_kind(deps.find("whisper-cli")) if WINDOWS else None
    return {"cuda": " (CUDA GPU)", "vulkan": " (Vulkan GPU)", "cpu": " (CPU)"}.get(kind, "")

def doctor(a):
    t = MSG[a.lang or lang_default()]
    print(f"== lsk doctor  (COURSE_ROOT = {ROOT})")
    ok = sys.version_info >= (3, 9)
    py_fix = "  " + t["py_old"].format(v=sys.version.split()[0]) + (f"  {t['how']}: winget install Python.Python.3.12  |  https://www.python.org/downloads/" if WINDOWS else "")
    print(f"  {'✅' if ok else '❌'} python {sys.version.split()[0]}" + ("" if ok else py_fix))
    slides = have("pdftotext") or has_module("pypdf")
    pdf_fix = deps.how("poppler") if WINDOWS else f"{deps.how('poppler')}  |  pip3 install pypdf"
    print(f"  {'✅' if slides else '➖'} pdftotext / pypdf ({t['optional']})" + ("" if slides else f"  {t['how']}: {pdf_fix}"))
    clients = [c for c in ("codex", "claude", "gemini") if have(c)]
    model = os.path.join(MODEL_DIR, "ggml-" + os.environ.get("WHISPER_MODEL", "large-v3-turbo") + ".bin")
    video = [("ffmpeg", have("ffmpeg") and have("ffprobe"), deps.how("ffmpeg")),
             ("whisper-cli" + win_build(), have("whisper-cli"), deps.how("whisper-cli")),
             ("tesseract", have("tesseract"), deps.how("tesseract")),
             ("Pillow", has_module("PIL"), deps.how("pillow")),
             (f"whisper model {os.path.basename(model)}", os.path.isfile(model), None)]
    for name, good, fix in video:
        if fix is None: print(f"  {'✅' if good else '➖'} {name}" + ("" if good else "  " + t["model_auto"])); continue
        print(f"  {'✅' if good else '❌'} {name}" + ("" if good else f"  {t['how']}: {fix}"))
    print("  " + (t["clients"].format(c=", ".join(clients)) if clients else t["no_client"]))
    print("== " + (t["sub_ready"] if ok else t["py_old"].format(v=sys.version.split()[0])))
    if not slides: print("   " + t["slides_none"])
    missing = [n for n, g, _ in video[:4] if not g]   # 模型首次运行会自动下载,不算缺
    print("== " + (t["vid_ready"] if not missing else t["vid_missing"].format(n=len(missing))))
    if missing or not os.path.isfile(model): print("   " + t["setup"].format(w=" (+ whisper.cpp)" if WINDOWS else ""))
    if WINDOWS and deps.whisper_win_kind(deps.find("whisper-cli")) == "cpu" and (gpu := deps.gpus()):
        print("   " + t["gpu_hint"].format(g=", ".join(gpu)))
    if not ok: return 1
    return 2 if (a.video and missing) else 0

# ---------- run ----------
VTT_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")

def vtt_to_srt(text):
    """WebVTT → SRT:去掉头部和样式块,时间补全小时、点改逗号,重新编号"""
    blocks, out = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()), []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None: continue                                   # WEBVTT 头、NOTE、STYLE
        def fix(m): return f"{int(m[1] or 0):02d}:{m[2]}:{m[3]},{m[4]}"
        start, _, end = lines[ti].partition("-->")
        ts = VTT_TS.sub(fix, start.strip()) + " --> " + VTT_TS.sub(fix, end.strip().split()[0])
        body = [re.sub(r"<[^>]+>", "", l) for l in lines[ti + 1:]]
        out.append(f"{len(out) + 1}\n{ts}\n" + "\n".join(body))
    return "\n\n".join(out) + "\n"

def lecture_name(src, unit, date):
    """优先用原文件名(能被 course_meta 解析时);否则用 --unit/--date 拼成 '<单元> <YYYY-MM-DD>'"""
    stem = os.path.splitext(os.path.basename(src))[0]
    cfg = course_meta.load_config(ROOT)
    if not (unit or date):
        r = course_meta.parse(stem, cfg)
        if r and r.get("date"): return stem
    if not (unit and date):
        sys.exit("错误 / Error: 无法从文件名看出单元和日期,请加 --unit DEMO1001 --date 2026-08-26\n"
                 "        cannot tell the unit and date from the file name; add --unit DEMO1001 --date 2026-08-26")
    if not re.fullmatch(r"[A-Z]{4}\d{4}", unit): sys.exit(f"错误 / Error: --unit 应形如 DEMO1001,收到 {unit}")
    try: datetime.date.fromisoformat(date)
    except ValueError: sys.exit(f"错误 / Error: --date 应形如 2026-08-26,收到 {date}")
    return f"{unit} {date}"

def slides_text(path):
    """课件 PDF → [(页码, 文字)];pdftotext 优先,其次 pypdf;都没有返回 None"""
    if have("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True, text=True, **UTF8)
        if r.returncode == 0: return list(enumerate(r.stdout.split("\f"), 1))[:-1] or [(1, r.stdout)]
    if has_module("pypdf"):
        import pypdf
        return [(i, p.extract_text() or "") for i, p in enumerate(pypdf.PdfReader(path).pages, 1)]
    return None

def write_slides_md(pdfs, out):
    parts = []
    for pdf in pdfs:
        pages = slides_text(pdf)
        if pages is None: print("  ⚠️ 没有 pdftotext / pypdf,跳过课件文字(见 lsk doctor)"); return None
        parts.append(f"# 课件文字:{os.path.basename(pdf)}(共 {len(pages)} 页)\n")
        for n, txt in pages:
            body = "\n".join(l.rstrip() for l in txt.strip().splitlines() if l.strip())
            parts.append(f"## p{n}/{len(pages)} {os.path.splitext(os.path.basename(pdf))[0]}\n\n{body or '(本页没有可提取的文字,可能以图片为主)'}\n")
    with open(out + ".tmp", "w", encoding="utf-8") as f: f.write("\n".join(parts))
    os.replace(out + ".tmp", out); return out

def find_slides(arg):
    if arg:
        if os.path.isdir(arg): return sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.lower().endswith(".pdf"))
        if os.path.isfile(arg): return [arg]
        sys.exit(f"错误 / Error: 找不到课件 {arg}")
    return []   # 没给就不读;课件文件夹里通常是整学期的课件,自动全读会塞满上下文

def run(a):
    src = a.input
    if not os.path.isfile(src):
        alt = os.path.join(ROOT, "课程视频", src)
        if os.path.isfile(alt): src = alt
        else: sys.exit(f"错误 / Error: 找不到文件 {a.input}")
    ext = os.path.splitext(src)[1].lower()
    if ext in VIDEO_EXTS:
        if WINDOWS:   # Windows 用 Python 版;macOS / Linux 仍用原来的 bash 版
            print("== 视频模式(实验性)/ video mode (experimental) → prepare.py")
            return subprocess.call([sys.executable, os.path.join(TOOLS, "prepare.py"), src, a.lang_code], env=child_env())
        print("== 视频模式(实验性)/ video mode (experimental) → prepare.sh")
        return subprocess.call(["bash", os.path.join(TOOLS, "prepare.sh"), src, a.lang_code], env=child_env())
    if ext not in (".srt", ".vtt"): sys.exit(f"错误 / Error: 只支持 .srt / .vtt 字幕或视频文件,收到 {ext}")
    name = lecture_name(src, a.unit, a.date)
    vdir = os.path.join(ROOT, "课程视频"); os.makedirs(vdir, exist_ok=True)
    srt = os.path.join(vdir, name + ".srt")
    text = open(src, encoding="utf-8", errors="ignore").read()
    if ext == ".vtt" or text.lstrip("﻿").startswith("WEBVTT"): text = vtt_to_srt(text.lstrip("﻿"))
    if os.path.exists(srt) and os.path.realpath(srt) != os.path.realpath(src):
        if open(srt, encoding="utf-8", errors="ignore").read() != text and not a.force:
            sys.exit(f"错误 / Error: {srt} 已存在且内容不同;确认要替换就加 --force")
    if os.path.realpath(srt) != os.path.realpath(src):
        with open(srt, "w", encoding="utf-8") as f: f.write(text)
    print(f"== 1/3 字幕 / subtitles → {os.path.relpath(srt, ROOT)}")
    for step, cmd in (("2/3 compact", [sys.executable, os.path.join(TOOLS, "compact.py"), srt]),
                      ("3/3 讲义稿 / transcript script", [sys.executable, os.path.join(TOOLS, "build_bundle.py"), srt, "--frames-dir", os.path.join(ROOT, "画面", name)])):
        print(f"== {step}")
        r = subprocess.run(cmd, env=child_env(), capture_output=True, text=True, **UTF8)
        if r.returncode != 0: sys.stderr.write(r.stdout + r.stderr); sys.exit(f"错误 / Error: {step} 失败")
    meta = course_meta.parse(name, course_meta.load_config(ROOT)) or {}
    slides = None
    pdfs = find_slides(a.slides)
    if pdfs: slides = write_slides_md(pdfs, os.path.join(vdir, name + ".slides.md"))
    lang = a.lang or meta.get("output_lang")
    notes = {"zh": meta.get("notes_path"), "en": meta.get("notes_path_en")}
    print("== 完成 / done")
    print(f"   讲义稿 / transcript script: {os.path.relpath(os.path.join(vdir, name + '.grounded.md'), ROOT)}")
    if slides: print(f"   课件逐页文字 / slide text: {os.path.relpath(slides, ROOT)}")
    if meta.get("week"): print(f"   单元 {meta['unit']} · {meta['date']} · 第 {meta['week']} 周 / week {meta['week']}")
    if lang in ("zh", "en"): print(f"   总结存 / save summary to: {notes[lang]}")
    else: print(f"   总结存 / save summary to: {notes['zh']}(中文)  |  {notes['en']}(English)  ← 语言没定,先问用户 / ask the user which language")
    print("   写完后 / when written: lsk finish \"<总结路径 / summary path>\"")
    return 0

# ---------- setup ----------
def setup(a):
    """视频模式的一次性准备:Windows 上装 whisper.cpp(默认 Vulkan GPU 版 + CPU 兜底);所有系统下载 whisper 模型(默认约 1.6 GB)与 VAD 模型。完成后再跑一遍 doctor --video"""
    if WINDOWS:                                        # 默认装 Vulkan 版(任何厂商的显卡都能用);再装 CPU 版兜底(GPU 版启动不了时转写自动换它)
        kind = "cpu" if a.cpu else "cuda" if a.cuda else "vulkan"
        if kind == "vulkan" and not (os.path.isfile(deps.WHISPER_WIN["vulkan"]["file"]) or os.environ.get("LSK_WHISPER_VULKAN_ZIP")):
            print("== ⚠️ 安装包里没有 GPU 版 whisper.cpp(vendor/),先装 CPU 版;请用 Windows 版安装包 / GPU build missing from vendor/, using CPU build"); kind = "cpu"
        if kind != "cpu": deps.install_whisper_windows(kind)
        deps.install_whisper_windows("cpu")
    elif not have("whisper-cli"):
        print(f"== 先安装 whisper.cpp / install whisper.cpp first: {deps.how('whisper-cli')}")
    name = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
    print(f"== 模型 / model: ggml-{name}.bin → {MODEL_DIR}")
    model = deps.ensure_model(name); deps.ensure_vad()
    cli = deps.find("whisper-cli")
    if cli:                                            # 试跑 1 秒静音,看实际用上的是 GPU 还是 CPU
        print("== 试跑 whisper.cpp / test run ...")
        ok, backend, gpu, tail = deps.probe_whisper(cli, model)
        if not ok: print(f"   ⚠️ whisper.cpp{win_build()} 启动失败 / failed to start" + (",转写时会自动改用 CPU 版 / will fall back to the CPU build" if WINDOWS else "") + f":\n{tail}")
        elif backend: print(f"   ✅ GPU 转写 / GPU transcription: {gpu or backend}({backend})")
        else: print("   ⚠️ 没用上显卡,转写走 CPU(慢)/ no usable GPU, transcription runs on the CPU (slow)" +
                    (f"。检测到的显卡 / GPUs: {', '.join(deps.gpus()) or '无 / none'};先更新显卡驱动再重跑 lsk setup / update the GPU driver and run lsk setup again" if WINDOWS else ""))
    a.video = True
    return doctor(a)

# ---------- install ----------
SKILL_DIRS = [os.path.join(os.path.expanduser("~"), *d) for d in ((".claude", "skills"), (".codex", "skills"), (".agents", "skills"))]   # 与 install.sh 相同

def link_skill(src, parent):
    """在 parent 下建 video-summary → src 的目录联接(junction:不需要管理员或开发者模式);已是链接就换成新的,是真目录就跳过"""
    dst = os.path.join(parent, "video-summary")
    os.makedirs(parent, exist_ok=True)
    if os.path.lexists(dst):
        try: os.readlink(dst)                          # Python 3.8+ 在 Windows 上也能读 junction;普通目录会抛 OSError
        except (OSError, ValueError):
            print(f"   {dst} 已存在且不是链接,跳过(如需替换请先手动删除) / exists and is not a link, skipped"); return False
        try: os.remove(dst)                            # 删的是链接本身,不动目标(符号链接用 remove,Windows 的 junction 要 rmdir)
        except OSError: os.rmdir(dst)
    if WINDOWS: ok = subprocess.run(["cmd", "/c", "mklink", "/J", dst, src], capture_output=True, **UTF8).returncode == 0
    else: os.symlink(src, dst); ok = True
    print(f"   {dst} -> {src}" if ok else f"   ❌ 链接失败 / link failed: {dst}")
    return ok

def install(a):
    if not WINDOWS: return subprocess.call(["bash", os.path.join(os.path.dirname(TOOLS), "install.sh")])
    if not a.skills_only:
        print("== 1/3 依赖 / dependencies (ffmpeg, tesseract, pillow, pypdf)")
        winget = shutil.which("winget")
        for cmd, pkg in (("ffmpeg", "Gyan.FFmpeg"), ("tesseract", "UB-Mannheim.TesseractOCR")):
            if have(cmd): print(f"   {cmd} 已安装 / installed"); continue
            if not winget: print(f"   ❌ 没有 winget,请手动安装 {cmd} / no winget, install {cmd} manually: https://learn.microsoft.com/windows/package-manager/winget/"); continue
            subprocess.call([winget, "install", "-e", "--id", pkg, "--accept-package-agreements", "--accept-source-agreements"])
        mods = [p for m, p in (("PIL", "pillow"), ("pypdf", "pypdf")) if not has_module(m)]
        if mods: subprocess.call([sys.executable, "-m", "pip", "install", "--user", *mods])
        print("== 2/3 whisper.cpp + 模型 / models")
        rc = setup(a)
        if rc: print("== 上面还有 ❌ 项;winget 刚装的程序如果没找到,关掉这个窗口、新开一个再运行 install.cmd / if something is still missing, open a new window and run install.cmd again")
    print("== 3/3 技能 / skill → Claude Code, Codex")
    src = os.path.join(os.path.dirname(TOOLS), "skills", "video-summary")
    ok = all([link_skill(src, d) for d in SKILL_DIRS])
    print("== 完成。之后在 Claude Code / Codex 里说「总结 <字幕或视频文件路径>」即可;移动本文件夹后要重跑 install.cmd")
    print("   Done. In Claude Code / Codex, say \"summarize <subtitle or video path>\"; run install.cmd again if you move this folder.")
    return 0 if ok else 1

# ---------- finish / review ----------
def finish(a):
    env = child_env()
    s = a.summary
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "add_links.py"), s], env=env, capture_output=True, text=True, **UTF8)
    print("== 回跳链接 / links: " + (r.stdout.strip() or r.stderr.strip()))   # 没有视频时会跳过,不算失败
    rc = subprocess.call([sys.executable, os.path.join(TOOLS, "check_summary.py"), s], env=env)
    subprocess.call([sys.executable, os.path.join(TOOLS, "exam_bank.py"), s, "--quiet"], env=env)
    print("== 考点库已更新 / exam bank updated" if rc == 0 else "== 检查没通过,先改总结再重跑 lsk finish / fix the summary and run lsk finish again")
    return rc

def review(a):
    return subprocess.call([sys.executable, os.path.join(TOOLS, "review_pack.py"), a.summary], env=child_env())

def main():
    ap = argparse.ArgumentParser(prog="lsk", description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("doctor"); d.add_argument("--video", action="store_true"); d.add_argument("--lang", choices=H.LANGS)
    u = sp.add_parser("setup"); u.add_argument("--lang", choices=H.LANGS); u.add_argument("--cpu", action="store_true", help="Windows: 只用 CPU 版"); u.add_argument("--cuda", action="store_true", help="Windows: NVIDIA 官方 CUDA 版(约 675 MB)")
    r = sp.add_parser("run"); r.add_argument("input"); r.add_argument("--unit"); r.add_argument("--date"); r.add_argument("--slides")
    r.add_argument("--lang", choices=H.LANGS, help="总结语言 / summary language"); r.add_argument("--lang-code", default="en", help="视频模式转写语言码 en/zh/auto"); r.add_argument("--force", action="store_true")
    i = sp.add_parser("install"); i.add_argument("--skills-only", action="store_true"); i.add_argument("--lang", choices=H.LANGS); i.add_argument("--cpu", action="store_true"); i.add_argument("--cuda", action="store_true")
    f = sp.add_parser("finish"); f.add_argument("summary")
    v = sp.add_parser("review"); v.add_argument("summary")
    a = ap.parse_args()
    sys.exit({"doctor": doctor, "setup": setup, "install": install, "run": run, "finish": finish, "review": review}[a.cmd](a))

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace")   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()
