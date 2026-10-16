#!/usr/bin/env python3
"""一键预处理一节录播:转写(VAD+术语表)‖抓帧 → compact → 帧去重 → OCR → bundle/讲义稿(Windows 版;macOS / Linux 仍用 prepare.sh。两份实现参数与产物一致,改一边要同步改另一边)
用法: prepare.py <视频文件名或路径> [语言码,默认 en]
  文件名不带路径时依次在 课程视频/ 和 ~/Downloads/ 找;在 Downloads 找到会先移入 课程视频/
  工作目录 = COURSE_ROOT,未设置时为本脚本所在 工具/ 的上级目录
  环境变量: FORCE=1 忽略已有产物全部重做;FRAME_MODE=12s 抓帧模式(默认 12s);NO_VAD=1 / GLOSSARY=<文件> 透传给 transcribe.py
  双路录像(UWA LMS 常见:<名>.mp4 是讲台电脑屏幕,<名>-2.mp4 是实物投影仪/摄像头):自动识别同目录的 <名>-2.<ext>(或 CAM=<路径> 指定);
    声音取两路里更响的那一路(有的课屏幕那路是静音的),产物仍归主文件名;实物投影那路用 cam_frames.py 挑手写页进 画面/<名>/cam/
  跳过规则: 只有"转写"和"抓帧"两步在已有产物时跳过;compact、OCR(增量)、课件匹配、bundle 每次都重跑(都只要几秒)
  帧去重只在本次真的抓了帧之后跑一次:dedup_frames 不是幂等的(删掉中间帧后前后两帧会落进同一窗口再被合并),重跑会把总结已引用的截图删掉
产出(全部在 课程视频/ 与 画面/):
  <名>.srt/.txt/.compact.txt  画面/<名>/*.jpg + ocr.json  <名>.bundle.json  <名>.grounded.md
"""
import glob, json, os, re, shutil, subprocess, sys, time
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import deps, course_meta
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(TOOLS)
PY = sys.executable

def die(msg): print(msg, file=sys.stderr); sys.exit(1)
def child_env(**kw): return dict(os.environ, COURSE_ROOT=ROOT, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", **kw)
def tool(script, *args, check=True, **kw):
    r = subprocess.run([PY, os.path.join(TOOLS, script), *args], env=child_env(), **kw)
    if check and r.returncode != 0: die(f"错误: {script} 失败(退出码 {r.returncode})")
    return r

def move_in(path, what="视频"):
    """把不在 课程视频/ 的文件移进去(同名已存在就不覆盖、报错)"""
    vdir = os.path.join(ROOT, "课程视频")
    if os.path.realpath(os.path.dirname(os.path.abspath(path))) == os.path.realpath(vdir): return path
    dest = os.path.join(vdir, os.path.basename(path))
    if os.path.exists(dest): die(f"错误: 课程视频/ 已有同名文件 {os.path.basename(path)},不覆盖;请先处理")
    print(f"== {what}不在 课程视频/,移入以保持产物集中"); shutil.move(path, dest); return dest

def locate(arg):
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.isfile(arg): return move_in(arg)
    if os.path.isfile(os.path.join(ROOT, "课程视频", arg)): return os.path.join(ROOT, "课程视频", arg)
    if os.path.isfile(os.path.join(downloads, arg)):
        print("== 在 Downloads 找到,移入 课程视频/"); return move_in(os.path.join(downloads, arg))
    die(f"错误: 找不到 {arg}(查过 课程视频/ 与 ~/Downloads/)")

def ffprobe_out(*args):
    return subprocess.run([deps.exe("ffprobe"), "-v", "error", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout

def mean_db(f):
    """响度取样:在 20%/50%/80% 三处各测 4 分钟的 mean_volume,取中位数(只测开头会被试麦/开场前的空档误导)"""
    try: dur = int(float(ffprobe_out("-show_entries", "format=duration", "-of", "csv=p=0", f).strip() or 0))
    except ValueError: dur = 0
    vals = []
    for frac in (20, 50, 80):
        r = subprocess.run([deps.exe("ffmpeg"), "-v", "info", "-ss", str(dur * frac // 100), "-t", "240", "-vn", "-sn", "-dn", "-i", f,
                            "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"mean_volume: ([-0-9.]+)", r.stderr)
        vals.append(m[1] if m else "-99")
    return sorted(vals, key=float)[1]

def frame_count(d): return len(glob.glob(os.path.join(glob.escape(d), "*.jpg"))) if os.path.isdir(d) else 0

def tail(path, n):
    if os.path.isfile(path):
        for l in open(path, encoding="utf-8", errors="replace").read().splitlines()[-n:]: print("   " + l)

def main():
    if len(sys.argv) < 2: die("用法: prepare.py <视频文件名或路径> [语言码]")
    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    mode = os.environ.get("FRAME_MODE", "12s"); force = os.environ.get("FORCE", "0") == "1"
    for d in ("课程视频", "画面", "总结"): os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    if not deps.find("ffmpeg") or not deps.find("ffprobe"): die(f"错误: 找不到 ffmpeg / ffprobe;安装: {deps.how('ffmpeg')}(装完运行 lsk doctor --video 检查)")
    video = locate(sys.argv[1])
    base, ext = os.path.splitext(video); name = os.path.basename(base)
    cam = os.environ.get("CAM", "")                   # 第二路(实物投影/摄像头)
    if not cam:
        cam = next((c for c in (f"{base}-2{ext}", os.path.join(os.path.expanduser("~"), "Downloads", f"{name}-2{ext}")) if os.path.isfile(c)), "")
    if cam and not os.path.isfile(cam): die(f"错误: CAM 指定的文件不存在: {cam}")
    if cam:
        cam = move_in(cam, "第二路录像")
        print(f"== 双路录像: 屏幕={os.path.basename(video)}  实物投影={os.path.basename(cam)}")
    frames = os.path.join(ROOT, "画面", name)
    fresh_frames = False
    is_video = "video" in ffprobe_out("-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", video)
    t0 = time.time()
    print(f"== 预处理: {name} (语言 {lang}, 抓帧模式 {mode}, 有画面: {int(is_video)})", flush=True)

    audio_src = video
    if cam:
        d1, d2 = mean_db(video), mean_db(cam)
        if float(d2) > float(d1) + 6: audio_src = cam
        print(f"== 声音: 屏幕路 {d1} dB,实物投影路 {d2} dB(20%/50%/80% 处各 4 分钟的中位数)→ 用 {os.path.basename(audio_src)} 转写")
    jobs = []                                         # (进程, 日志文件)
    def bg(script, args, logf, **env):
        fh = open(logf, "w", encoding="utf-8")
        jobs.append((subprocess.Popen([PY, os.path.join(TOOLS, script), *args], stdout=fh, stderr=subprocess.STDOUT, env=child_env(**env)), fh))
    logs = {k: f"{base}.{k}.log" for k in ("transcribe", "frames", "cam")}
    if force or not (os.path.isfile(base + ".srt") and os.path.getsize(base + ".srt") > 0):
        print("== [1/5] 转写 (后台)", flush=True); bg("transcribe.py", [audio_src, lang], logs["transcribe"], OUT_BASE=base)
    else: print(f"== [1/5] 转写: 已有 {name}.srt,跳过(FORCE=1 可重做)")
    if is_video:
        if force or frame_count(frames) == 0:
            print("== [2/5] 抓帧 (后台)", flush=True); bg("extract_frames.py", [video, mode, frames], logs["frames"]); fresh_frames = True
        else: print(f"== [2/5] 抓帧: 画面/{name} 已有帧,跳过(FORCE=1 可重做)")
        if cam:
            if force or not (os.path.isfile(os.path.join(frames, "cam", "cam.json")) and os.path.getsize(os.path.join(frames, "cam", "cam.json")) > 0):
                print("== [2b] 实物投影手写帧 (后台)", flush=True); bg("cam_frames.py", [cam, os.path.join(frames, "cam")], logs["cam"])
            else: print(f"== [2b] 手写帧: 画面/{name}/cam 已有,跳过(FORCE=1 可重做)")
    fail = False
    for p, fh in jobs:
        fail |= p.wait() != 0; fh.close()
    if fail: die(f"错误: 转写或抓帧失败,看 {logs['transcribe']} / {logs['frames']} / {logs['cam']}")
    tail(logs["transcribe"], 2); tail(logs["frames"], 1); tail(logs["cam"], 1)

    print("== [3/5] compact", flush=True); tool("compact.py", base + ".srt")
    if is_video and os.path.isdir(frames):
        print("== [4/5] 帧去重 + OCR", flush=True)
        if fresh_frames: tool("dedup_frames.py", frames)
        else: print("   去重: 本次未重新抓帧,跳过(去重不幂等,重跑会删掉已引用的帧)")
        tool("ocr_frames.py", frames, *(["--force"] if force else []))
    # 课件 PDF 匹配(可选):course.json 里该单元配了 slides_dir 且目录里有 PDF 时,用课件文字给帧定页码
    try: meta = course_meta.parse(os.path.basename(video), course_meta.load_config(ROOT))
    except SystemExit: meta = None
    slides_dir = (meta or {}).get("slides_dir") or ""
    if is_video and slides_dir:
        pdfs = glob.glob(os.path.join(glob.escape(os.path.join(ROOT, slides_dir)), "*.pdf"))
        if not deps.find("pdftotext") and not _has_pypdf():
            print(f"   ⚠️ course.json 配了课件目录 {slides_dir},但没有 pdftotext 也没有 pypdf({deps.how('poppler')}),跳过课件匹配", file=sys.stderr)
            tool("match_slides.py", frames, "--clear", check=False, stdout=subprocess.DEVNULL)
        elif not pdfs:
            print(f"   ⚠️ course.json 配了课件目录 {slides_dir},但里面没有 PDF,跳过课件匹配", file=sys.stderr)
            tool("match_slides.py", frames, "--clear", check=False, stdout=subprocess.DEVNULL)
        else:
            print(f"== [4b] 课件 PDF 匹配 ({slides_dir})", flush=True)
            if tool("match_slides.py", frames, os.path.join(ROOT, slides_dir), check=False).returncode != 0:
                print("   ⚠️ 课件匹配失败,继续用工具栏页码", file=sys.stderr)
    elif is_video and os.path.isfile(os.path.join(frames, "ocr.json")):   # 没配课件:清掉以前的匹配结果,避免陈旧引用
        tool("match_slides.py", frames, "--clear", check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("== [5/5] bundle + 讲义稿", flush=True); tool("build_bundle.py", video)
    for f in logs.values():
        if os.path.exists(f): os.remove(f)
    notes = f"总结/<单元代码>/{name}.md"
    if meta:
        r = tool("course_meta.py", video, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"== 课程信息: {(r.stdout.splitlines() or [''])[0]}")
        notes = meta["notes_path_en"] if meta.get("output_lang") == "en" else meta["notes_path"]
    print(f"== 全部完成,用时 {int(time.time() - t0)} 秒。下一步:读 {base}.grounded.md 写总结,总结存 {notes}(英文总结用 .en.md 结尾,语言优先级见 policy.md),写完跑 lsk finish \"<总结路径>\"")

def _has_pypdf():
    try: import pypdf; return True
    except ImportError: return False

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()
