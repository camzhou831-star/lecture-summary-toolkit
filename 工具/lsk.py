#!/usr/bin/env python3
"""lsk — 课程总结工具的总入口(给智能体和新手用;一次调用做完一个阶段,不用记各个脚本)
用法:
  lsk doctor [--video] [--lang zh|en]          检查环境:字幕模式要什么、视频模式还缺什么,缺的给出安装命令
  lsk run <字幕.srt|.vtt|视频> [--unit DEMO1001 --date 2026-08-26] [--slides <课件.pdf|目录>] [--lang en] [--force]
                                               字幕模式:放好字幕 → compact → 讲义稿(+ 课件逐页文字);视频模式调用 prepare.sh(实验性)
  lsk finish <总结.md>                          写完总结后:加回跳链接 → 检查 → 重生成考点库
  lsk review <总结.md>                          准备审核包(见 skills/video-summary/review.md)
目录:COURSE_ROOT 环境变量,默认是本工具目录;字幕、讲义稿在 课程视频/,总结在 总结/<单元>/
"""
import argparse, datetime, os, re, shutil, subprocess, sys
TOOLS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, TOOLS)
import course_meta, headings as H
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(TOOLS)
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav")
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR") or os.path.expanduser("~/.local/share/whisper-models")

MSG = {
    "zh": {"ok": "可用", "missing": "缺少", "optional": "可选", "sub_ready": "字幕模式:可以用(只需要 Python)。",
           "vid_ready": "视频模式:可以用。", "vid_missing": "视频模式(实验性):还缺 {n} 项,装好后再用;只有字幕的话不用装。",
           "slides_none": "读课件 PDF 需要 pdftotext(poppler)或 Python 包 pypdf,二选一;没有的话只用字幕也能总结。",
           "clients": "检测到的 AI 客户端:{c}", "no_client": "没检测到命令行版 AI 客户端(Codex / Claude Code / Gemini CLI);用桌面版也可以,打开本文件夹即可。",
           "py_old": "Python 版本太旧({v}),需要 3.9 以上", "how": "安装命令", "model_auto": "第一次处理视频时自动下载(约 1.6 GB)"},
    "en": {"ok": "ready", "missing": "missing", "optional": "optional", "sub_ready": "Subtitle mode: ready (only needs Python).",
           "vid_ready": "Video mode: ready.", "vid_missing": "Video mode (experimental): {n} item(s) missing. Not needed if you only have subtitles.",
           "slides_none": "Reading slide PDFs needs pdftotext (poppler) or the Python package pypdf; without them, subtitles alone still work.",
           "clients": "AI clients found: {c}", "no_client": "No command-line AI client found (Codex / Claude Code / Gemini CLI); a desktop app also works: open this folder in it.",
           "py_old": "Python is too old ({v}); 3.9 or newer is required", "how": "install with", "model_auto": "downloaded automatically on the first video run (about 1.6 GB)"},
}

def lang_default():
    return "zh" if (os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")).lower().startswith("zh") else "en"

def have(cmd): return shutil.which(cmd) is not None

def has_module(m):
    try: __import__(m); return True
    except ImportError: return False

# 安装命令:macOS 用 Homebrew;Linux 的 apt 包名不同,whisper.cpp 没有 apt 包
INSTALL = {"poppler": ("brew install poppler", "sudo apt-get install poppler-utils"),
           "ffmpeg": ("brew install ffmpeg", "sudo apt-get install ffmpeg"),
           "whisper-cpp": ("brew install whisper-cpp", "build from https://github.com/ggml-org/whisper.cpp and put whisper-cli on PATH"),
           "tesseract": ("brew install tesseract", "sudo apt-get install tesseract-ocr")}
def brew_or(pkg):
    mac, linux = INSTALL[pkg]
    return mac if sys.platform == "darwin" or have("brew") else linux

def doctor(a):
    t = MSG[a.lang or lang_default()]
    print(f"== lsk doctor  (COURSE_ROOT = {ROOT})")
    ok = sys.version_info >= (3, 9)
    print(f"  {'✅' if ok else '❌'} python3 {sys.version.split()[0]}" + ("" if ok else "  " + t["py_old"].format(v=sys.version.split()[0])))
    slides = have("pdftotext") or has_module("pypdf")
    print(f"  {'✅' if slides else '➖'} pdftotext / pypdf ({t['optional']})" + ("" if slides else f"  {t['how']}: {brew_or('poppler')}  |  pip3 install pypdf"))
    model = os.path.join(MODEL_DIR, "ggml-" + os.environ.get("WHISPER_MODEL", "large-v3-turbo") + ".bin")
    video = [("ffmpeg", have("ffmpeg") and have("ffprobe"), brew_or("ffmpeg")),
             ("whisper-cli", have("whisper-cli"), brew_or("whisper-cpp")),
             ("tesseract", have("tesseract"), brew_or("tesseract")),
             ("Pillow", has_module("PIL"), "pip3 install pillow"),
             (f"whisper model {os.path.basename(model)}", os.path.isfile(model), None)]
    for name, good, fix in video:
        if fix is None: print(f"  {'✅' if good else '➖'} {name}" + ("" if good else "  " + t["model_auto"])); continue
        print(f"  {'✅' if good else '❌'} {name}" + ("" if good else f"  {t['how']}: {fix}"))
    clients = [c for c in ("codex", "claude", "gemini") if have(c)]
    print("  " + (t["clients"].format(c=", ".join(clients)) if clients else t["no_client"]))
    print("== " + (t["sub_ready"] if ok else t["py_old"].format(v=sys.version.split()[0])))
    if not slides: print("   " + t["slides_none"])
    missing = [n for n, g, _ in video[:4] if not g]   # 模型首次运行会自动下载,不算缺
    print("== " + (t["vid_ready"] if not missing else t["vid_missing"].format(n=len(missing))))
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
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
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
        print("== 视频模式(实验性)/ video mode (experimental) → prepare.sh")
        env = dict(os.environ, COURSE_ROOT=ROOT)
        return subprocess.call(["bash", os.path.join(TOOLS, "prepare.sh"), src, a.lang_code], env=env)
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
        r = subprocess.run(cmd, env=dict(os.environ, COURSE_ROOT=ROOT), capture_output=True, text=True)
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

# ---------- finish / review ----------
def finish(a):
    env = dict(os.environ, COURSE_ROOT=ROOT)
    s = a.summary
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "add_links.py"), s], env=env, capture_output=True, text=True)
    print("== 回跳链接 / links: " + (r.stdout.strip() or r.stderr.strip()))   # 没有视频时会跳过,不算失败
    rc = subprocess.call([sys.executable, os.path.join(TOOLS, "check_summary.py"), s], env=env)
    subprocess.call([sys.executable, os.path.join(TOOLS, "exam_bank.py"), s, "--quiet"], env=env)
    print("== 考点库已更新 / exam bank updated" if rc == 0 else "== 检查没通过,先改总结再重跑 lsk finish / fix the summary and run lsk finish again")
    return rc

def review(a):
    return subprocess.call([sys.executable, os.path.join(TOOLS, "review_pack.py"), a.summary], env=dict(os.environ, COURSE_ROOT=ROOT))

def main():
    ap = argparse.ArgumentParser(prog="lsk", description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("doctor"); d.add_argument("--video", action="store_true"); d.add_argument("--lang", choices=H.LANGS)
    r = sp.add_parser("run"); r.add_argument("input"); r.add_argument("--unit"); r.add_argument("--date"); r.add_argument("--slides")
    r.add_argument("--lang", choices=H.LANGS, help="总结语言 / summary language"); r.add_argument("--lang-code", default="en", help="视频模式转写语言码 en/zh/auto"); r.add_argument("--force", action="store_true")
    f = sp.add_parser("finish"); f.add_argument("summary")
    v = sp.add_parser("review"); v.add_argument("summary")
    a = ap.parse_args()
    sys.exit({"doctor": doctor, "run": run, "finish": finish, "review": review}[a.cmd](a))

if __name__ == "__main__":
    main()
