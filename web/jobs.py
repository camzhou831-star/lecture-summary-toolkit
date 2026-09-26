"""任务:持久化记录 + 分阶段执行 + 指纹缓存 + 取消 + 重启后识别未完成任务。
恢复粒度是"阶段":已完成且输入/参数没变的阶段直接跳过;中断的阶段从头重跑(不支持阶段内部断点续传)。
一次只跑一个重任务(单个后台线程按队列执行)。"""
import os, queue, random, re, shutil, signal, string, subprocess, sys, threading, time, traceback
from .util import (TOOLS, atomic_write_json, read_json, data_root, file_fingerprint, fingerprint, now, which,
                   IS_WINDOWS, IS_MAC, VERSION)
from . import subtitles, pdftext, sources, materials, courses, models

STAGE_NAMES = {
    "check_env": "检查环境与磁盘空间", "model": "准备语音识别模型", "transcribe": "语音转写",
    "subtitle": "读取字幕", "frames": "抓取录播画面", "ocr": "识别画面文字", "slides": "读取课件",
    "sources": "整理来源编号", "material": "生成 AI 材料",
}
OCR_VERSION = "ocr_frames-v1"

class StageError(Exception):
    def __init__(self, what, next_step="", detail=""):
        super().__init__(what); self.what, self.next_step, self.detail = what, next_step, detail

class Cancelled(Exception):
    pass

def jobs_root():
    d = os.path.join(data_root(), "jobs"); os.makedirs(d, exist_ok=True); return d

def job_dir(jid):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{4}-[a-z0-9]{4}", jid or ""): raise KeyError(jid)
    return os.path.join(jobs_root(), jid)

_lock = threading.RLock()

def load(jid):
    return read_json(os.path.join(job_dir(jid), "job.json"))

def save(job):
    with _lock:
        job["updated"] = now()
        atomic_write_json(os.path.join(job_dir(job["id"]), "job.json"), job)

def update(jid, fn):
    with _lock:
        job = load(jid); fn(job); save(job); return job

def list_jobs():
    out = []
    for d in sorted(os.listdir(jobs_root()), reverse=True):
        j = read_json(os.path.join(jobs_root(), d, "job.json"))
        if j: out.append(j)
    return out

def new_id():
    return time.strftime("%Y%m%d-%H%M") + "-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=4))

def pipeline(job):
    mode = job["mode"]; has_video = bool(job["inputs"].get("video"))
    want_frames = has_video and job["options"].get("frames", True)
    if mode == "video":
        st = ["check_env", "model", "transcribe"] + (["frames", "ocr"] if want_frames else [])
    elif mode == "subtitle":
        st = ["subtitle"] + (["check_env", "frames", "ocr"] if want_frames else [])
    else:
        st = []
    if job["inputs"].get("slides") or mode == "slides": st.append("slides")
    return st + ["sources", "material"]

def create(fields):
    jid = new_id()
    d = os.path.join(jobs_root(), jid)
    for sub in ("inputs", "work", "logs", "ai"): os.makedirs(os.path.join(d, sub), exist_ok=True)
    job = {"id": jid, "created": now(), "updated": now(), "version": VERSION, "state": "draft", "current": None,
           "title": fields.get("title") or "", "course_id": fields.get("course_id") or "", "date": fields.get("date") or "",
           "mode": fields["mode"], "template": fields.get("template") or "full",
           "lang": fields.get("lang") or "en", "note_lang": fields.get("note_lang") or "zh",
           "inputs": {"video": None, "cam": None, "subtitle": None, "slides": []},
           "options": {"frames": True, "frame_mode": "12s", "whisper_model": models.DEFAULT_MODEL, "vad": True,
                       "chunk_chars": materials.DEFAULT_CHUNK_CHARS},
           "stages": {}, "notices": [], "material": None,
           "ai": {"parts": {}, "parts_n": 0, "versions": []}}
    save(job)
    return job

def describe_input(path):
    st = os.stat(path)
    return {"path": os.path.abspath(path), "name": os.path.basename(path), "size": st.st_size, "fp": file_fingerprint(path)}

# ---------------- 执行上下文 ----------------

class Ctx:
    def __init__(self, job, stage):
        self.jid, self.stage = job["id"], stage
        self.dir = job_dir(job["id"]); self.work = os.path.join(self.dir, "work")
        self.proc = None; self.cancelled = False
        self.log_path = os.path.join(self.dir, "logs", stage + ".log")
        open(self.log_path, "w").close()

    def log(self, msg):
        with open(self.log_path, "a", encoding="utf-8") as f: f.write(msg.rstrip("\n") + "\n")

    def progress(self, label, done=None, total=None):
        def fn(j):
            s = j["stages"].setdefault(self.stage, {})
            s["progress"] = {"label": label, "done": done, "total": total, "at": now()}
        update(self.jid, fn)

    def check_cancel(self):
        if self.cancelled: raise Cancelled()

    def run(self, cmd, env=None, cwd=None, poll=None):
        """运行子进程(参数列表,不经过 shell),输出写进阶段日志;poll() 每 2 秒调用一次用于更新进度"""
        self.check_cancel()
        e = dict(os.environ); e.update(env or {})
        e.setdefault("PYTHONIOENCODING", "utf-8")
        self.log("$ " + " ".join(cmd))
        with open(self.log_path, "a", encoding="utf-8") as lf:
            kw = {"start_new_session": True} if not IS_WINDOWS else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            self.proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=e, cwd=cwd, **kw)
            while True:
                try:
                    rc = self.proc.wait(timeout=2); break
                except subprocess.TimeoutExpired:
                    if self.cancelled: self.kill(); self.proc.wait(); raise Cancelled()
                    if poll:
                        try: poll()
                        except Exception: pass
        self.proc = None
        if self.cancelled: raise Cancelled()
        return rc

    def kill(self):
        p = self.proc
        if not p or p.poll() is not None: return
        try:
            if IS_WINDOWS: p.terminate()
            else: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def tail(self, n=15):
        try: return "\n".join(open(self.log_path, encoding="utf-8", errors="replace").read().splitlines()[-n:])
        except OSError: return ""

# ---------------- 各阶段 ----------------

def _python():
    return sys.executable or "python3"

def _duration(path):
    if not which("ffprobe"): return None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except ValueError: return None

def stage_check_env(job, ctx):
    need = []
    mode = job["mode"]
    if IS_WINDOWS:
        raise StageError("Windows 上暂时不能处理视频(转写和抓帧依赖 bash 与 macOS 上验证过的工具链)",
                         "改用「字幕」模式(从录播平台下载字幕文件)或「仅课件」模式;视频处理目前只支持 Mac")
    tools = ["bash", "ffmpeg", "ffprobe"]
    if mode == "video": tools.append("whisper-cli")
    if job["options"].get("frames", True) and job["inputs"].get("video"): tools.append("tesseract")
    missing = [t for t in tools if not which(t)]
    if missing:
        pk = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "whisper-cli": "whisper-cpp", "tesseract": "tesseract", "bash": "bash"}
        pkgs = " ".join(sorted({pk[m] for m in missing}))
        raise StageError(f"缺少处理视频需要的程序:{', '.join(missing)}",
                         f"Mac:在「终端」里运行 brew install {pkgs}(没有 Homebrew 先看 https://brew.sh),装好后点「重试」。"
                         + ("也可以改用字幕模式,不需要语音识别。" if mode == "video" else ""))
    v = job["inputs"]["video"]["path"]
    if not os.path.exists(v):
        raise StageError(f"找不到视频文件:{os.path.basename(v)}(可能被移动、改名或外接硬盘没插)", "点「重新选择文件」指定视频的新位置")
    dur = _duration(v)
    if not dur:
        raise StageError("无法读取视频时长,文件可能损坏或不是音视频文件", "确认视频能在播放器里正常播放;或重新下载录播")
    update(job["id"], lambda j: j.setdefault("info", {}).__setitem__("duration", dur))
    # 磁盘空间:模型(如需下载)+ 临时音频(16kHz 单声道约 32 KB/秒)+ 画面(每帧约 150 KB,最多 duration/12 张)
    need_bytes = int(dur * 32000) + int(dur / 12 * 150_000) + 200_000_000
    if mode == "video" and not models.present(job["options"]["whisper_model"]):
        need_bytes += models.size_hint(job["options"]["whisper_model"])
    free = shutil.disk_usage(ctx.dir).free
    ctx.log(f"duration={dur:.0f}s need≈{need_bytes/1e9:.2f}GB free={free/1e9:.1f}GB")
    if free < need_bytes:
        raise StageError(f"磁盘空间不够:大约需要 {need_bytes/1e9:.1f} GB,当前只剩 {free/1e9:.1f} GB",
                         "清理一些文件(比如下载文件夹里不用的视频)后点「重试」")

def stage_model(job, ctx):
    name = job["options"]["whisper_model"]
    def prog(label, done, total): ctx.progress(label, done, total); ctx.check_cancel()
    try:
        models.ensure(name, prog, log=ctx.log, vad=job["options"].get("vad", True))
    except models.DownloadError as e:
        raise StageError(str(e), "检查网络后点「重试」,已下载的部分会接着下载")

def _glossary_file(job, ctx):
    terms = courses.glossary(job.get("course_id"))
    if not terms: return None
    p = os.path.join(ctx.work, "glossary.txt")
    open(p, "w", encoding="utf-8").write(", ".join(terms) + ".")
    return p

def stage_transcribe(job, ctx):
    v = job["inputs"]["video"]["path"]
    part = os.path.join(ctx.work, ".partial-transcribe"); shutil.rmtree(part, ignore_errors=True); os.makedirs(part)
    env = {"OUT_BASE": os.path.join(part, "lecture"), "WHISPER_MODEL": job["options"]["whisper_model"]}
    if not job["options"].get("vad", True): env["NO_VAD"] = "1"
    g = _glossary_file(job, ctx)
    if g: env["GLOSSARY"] = g
    dur = (job.get("info") or {}).get("duration") or 0
    est = models.estimate("transcribe:" + job["options"]["whisper_model"], dur)
    t0 = time.time()
    def poll():
        el = time.time() - t0
        msg = f"转写中,已用 {int(el)//60} 分 {int(el)%60} 秒"
        if est: msg += f";按这台电脑以前的速度约需 {max(1, int(est)//60)} 分钟(仅供参考)"
        else: msg += ";第一次在这台电脑上转写,暂时无法预估剩余时间"
        ctx.progress(msg)
    poll()
    rc = ctx.run(["bash", os.path.join(TOOLS, "transcribe.sh"), v, job.get("lang") or "en"], env=env, poll=poll)
    srt = os.path.join(part, "lecture.srt")
    if rc != 0 or not os.path.exists(srt) or os.path.getsize(srt) == 0:
        raise StageError("语音转写失败", "点「重试」再试一次;如果一直失败,可以改用字幕模式,或导出诊断信息反馈", ctx.tail())
    for ext in (".srt", ".txt"):
        if os.path.exists(os.path.join(part, "lecture" + ext)): os.replace(os.path.join(part, "lecture" + ext), os.path.join(ctx.work, "lecture" + ext))
    shutil.rmtree(part, ignore_errors=True)
    models.record("transcribe:" + job["options"]["whisper_model"], dur, time.time() - t0)

def stage_subtitle(job, ctx):
    sub = job["inputs"]["subtitle"]
    if not os.path.exists(sub["path"]):
        raise StageError("找不到字幕文件", "点「重新选择文件」重新导入字幕")
    cues, fmt = subtitles.parse(subtitles.load_file(sub["path"]))
    dur = None
    if job["inputs"].get("video") and os.path.exists(job["inputs"]["video"]["path"]):
        dur = _duration(job["inputs"]["video"]["path"])
        if dur: update(job["id"], lambda j: j.setdefault("info", {}).__setitem__("duration", dur))
    good, issues = subtitles.check(cues, dur)
    def fn(j):
        j.setdefault("info", {})["subtitle_issues"] = issues
        j["info"]["subtitle_format"] = fmt
    update(job["id"], fn)
    if not good:
        raise StageError(issues[-1]["msg"] if issues else "字幕里没有可用内容", "点「重新选择文件」换一个字幕文件")
    from .util import atomic_write_text
    atomic_write_text(os.path.join(ctx.work, "lecture.srt"), subtitles.to_srt(good))
    ctx.log(f"subtitle {fmt}: {len(good)} cues, issues={issues}")

def stage_frames(job, ctx):
    v = job["inputs"]["video"]["path"]
    part = os.path.join(ctx.work, ".partial-frames"); shutil.rmtree(part, ignore_errors=True); os.makedirs(part)
    tmp = os.path.join(part, ".extract_tmp")
    def poll():
        n = len([f for f in os.listdir(tmp) if f.endswith(".jpg")]) if os.path.isdir(tmp) else 0
        ctx.progress(f"已抓取 {n} 张画面(最终会去掉重复的)", n, None)
    poll()
    rc = ctx.run(["bash", os.path.join(TOOLS, "extract_frames.sh"), v, job["options"].get("frame_mode", "12s"), part], poll=poll)
    if rc != 0:
        raise StageError("抓取画面失败", "点「重试」;如果视频只有声音没有画面,可以在高级设置里关闭「抓取画面」", ctx.tail())
    ctx.progress("去掉完全重复的画面")
    if ctx.run([_python(), os.path.join(TOOLS, "dedup_frames.py"), part]) != 0:
        raise StageError("画面去重失败", "点「重试」", ctx.tail())
    cam = job["inputs"].get("cam")
    if cam:
        ctx.progress("挑选手写页(第二路录像)")
        if ctx.run([_python(), os.path.join(TOOLS, "cam_frames.py"), cam["path"], os.path.join(part, "cam")]) != 0:
            ctx.log("⚠️ 手写页挑选失败,继续(不含手写页)")
            update(job["id"], lambda j: j["notices"].append("第二路录像的手写页挑选失败,本次不含手写页"))
    final = os.path.join(ctx.work, "frames")
    old = final + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(final): os.replace(final, old)
    os.replace(part, final)
    shutil.rmtree(old, ignore_errors=True)

def stage_ocr(job, ctx):
    frames = os.path.join(ctx.work, "frames")
    n = len([f for f in os.listdir(frames) if f.endswith(".jpg")]) if os.path.isdir(frames) else 0
    if n == 0:
        update(job["id"], lambda j: j["notices"].append("没有抓到可用的画面,笔记只基于转写"))
        return
    ctx.progress(f"识别 {n} 张画面的文字", 0, n)
    rc = ctx.run([_python(), os.path.join(TOOLS, "ocr_frames.py"), frames, "--jobs", "4"])
    if rc != 0:
        raise StageError("画面文字识别(OCR)失败", "点「重试」(转写结果已保存,不需要重新转写)", ctx.tail())

def stage_slides(job, ctx):
    decks, all_text = [], []
    for s in job["inputs"].get("slides", []):
        if not os.path.exists(s["path"]):
            raise StageError(f"找不到课件文件:{s['name']}", "点「重新选择文件」重新添加课件")
        try: pages = pdftext.extract_pages(s["path"])
        except pdftext.PdfError as e: raise StageError(e.what, e.next_step)
        stt = pdftext.text_status(pages)
        decks.append({"file": s["path"], "name": os.path.splitext(s["name"])[0], "pages": pages, "status": stt})
        all_text.append("\n".join(pages))
        ctx.log(f"{s['name']}: {len(pages)} pages, text={stt}")
    no_text = [d["name"] for d in decks if d["status"] == "none"]
    if no_text:
        msg = f"课件「{'、'.join(no_text)}」没有可提取的文字(可能是扫描版或图片 PDF)"
        if job["mode"] == "slides" and len(no_text) == len(decks):
            raise StageError(msg + ",无法生成基于课件的笔记",
                             "换一份带文字的 PDF(能在预览里选中文字的那种);或者直接把这份 PDF 上传给 AI 网页版,让它读图")
        update(job["id"], lambda j: j["notices"].append(msg + ",这些课件不会进入 AI 材料"))
        decks = [d for d in decks if d["status"] != "none"]
    partial = [d["name"] for d in decks if d["status"] == "partial"]
    if partial: update(job["id"], lambda j: j["notices"].append(f"课件「{'、'.join(partial)}」有一半以上的页没有文字,可能是扫描页,相关内容可能缺失"))
    from .util import atomic_write_json as awj
    awj(os.path.join(ctx.work, "slides.json"), decks)
    cands = courses.term_candidates("\n".join(all_text))
    update(job["id"], lambda j: j.setdefault("info", {}).__setitem__("glossary_candidates", cands))
    frames = os.path.join(ctx.work, "frames")
    if decks and os.path.exists(os.path.join(frames, "ocr.json")):
        if not which("pdftotext"):
            update(job["id"], lambda j: j["notices"].append("没有安装 poppler,无法把画面对上课件页码(brew install poppler);其余功能不受影响"))
            return
        ctx.progress("把录播画面对上课件页码")
        rc = ctx.run([_python(), os.path.join(TOOLS, "match_slides.py"), frames] + [d["file"] for d in decks])
        if rc != 0:
            update(job["id"], lambda j: j["notices"].append("画面与课件页码匹配失败,截图不带课件页码"))

def stage_sources(job, ctx):
    decks = read_json(os.path.join(ctx.work, "slides.json"), []) if (job["inputs"].get("slides") or job["mode"] == "slides") else []
    dur = (job.get("info") or {}).get("duration")
    reg = sources.build(ctx.dir, job["mode"], decks, bool(job["inputs"].get("video")), dur)
    if job["mode"] != "slides" and not reg["segments"]:
        raise StageError("转写/字幕里没有可用的文字(可能整段都是静音或被当成无效内容过滤了)",
                         "确认视频有声音、字幕文件是这节课的;字幕模式可以点「重新选择文件」")
    if job["mode"] == "slides" and not any(p["text"].strip() for d in reg["decks"] for p in d["pages"]):
        raise StageError("课件里没有可用的文字", "换一份带文字的 PDF")
    # 给 CLI 流程留一份讲义稿(grounded.md),与原工作流兼容
    if job["mode"] != "slides" and os.path.exists(os.path.join(ctx.work, "lecture.srt")):
        srt = os.path.join(ctx.work, "lecture.srt")
        ctx.run([_python(), os.path.join(TOOLS, "compact.py"), srt])
        cmd = [_python(), os.path.join(TOOLS, "build_bundle.py"), srt, "--frames-dir", os.path.join(ctx.work, "frames")]
        if dur: cmd += ["--duration", str(dur)]
        if ctx.run(cmd, env={"COURSE_ROOT": ctx.dir}) != 0:
            ctx.log("⚠️ build_bundle 失败(不影响网页流程)")
    update(job["id"], lambda j: j.setdefault("info", {}).update(
        {"n_segments": len(reg["segments"]), "n_frames": len(reg["frames"]), "n_cam": len(reg["cam"]),
         "n_pages": sum(len(d["pages"]) for d in reg["decks"]), "duration": reg.get("duration") or dur}))

def material_meta(job):
    c = courses.get(job.get("course_id")) or {}
    return {"job_id": job["id"], "title": job.get("title") or "", "course": c.get("name") or "", "date": job.get("date") or "",
            "glossary": courses.glossary(job.get("course_id")), "note_lang": job.get("note_lang"),
            "subtitle_source": "import" if job["mode"] == "subtitle" else "whisper",
            "material_filename": f"AI材料-{job['id']}.md"}

def stage_material(job, ctx):
    reg = sources.load(ctx.dir)
    meta = material_meta(job)
    full = materials.build_full(meta, reg)
    chunks = materials.build_chunks(meta, reg, int(job["options"].get("chunk_chars") or materials.DEFAULT_CHUNK_CHARS))
    from .util import atomic_write_text
    atomic_write_text(os.path.join(ctx.dir, "ai", "material.md"), full)
    for c in chunks: atomic_write_text(os.path.join(ctx.dir, "ai", f"chunk-{c['no']}.md"), c["text"])
    info = {"chars": len(full), "chunks": [{"no": c["no"], "range": c["range"], "chars": len(c["text"])} for c in chunks], "generated": now()}
    def fn(j):
        old_n = j["ai"].get("parts_n")
        j["material"] = info
        if old_n and old_n != len(chunks) and j["ai"].get("parts"):
            j["notices"].append("AI 材料的分块数量变了,之前粘贴的分块回复已作废,请按新的分块重新发送")
            j["ai"]["parts"] = {}
        j["ai"]["parts_n"] = len(chunks)
    update(job["id"], fn)

HANDLERS = {"check_env": stage_check_env, "model": stage_model, "transcribe": stage_transcribe, "subtitle": stage_subtitle,
            "frames": stage_frames, "ocr": stage_ocr, "slides": stage_slides, "sources": stage_sources, "material": stage_material}

def stage_fp(job, stage, fps):
    inp, opt = job["inputs"], job["options"]
    vfp = (inp.get("video") or {}).get("fp")
    deps = {
        "check_env": (vfp, job["mode"], opt.get("frames")),
        "model": (opt.get("whisper_model"), opt.get("vad")),
        # 术语表不进转写指纹:改术语不自动触发重新转写(2 小时课要几分钟);需要时在界面点「重新转写」
        "transcribe": (vfp, job.get("lang"), opt.get("whisper_model"), opt.get("vad"), job.get("force", {}).get("transcribe")),
        "subtitle": ((inp.get("subtitle") or {}).get("fp"), vfp),
        "frames": (vfp, opt.get("frame_mode"), (inp.get("cam") or {}).get("fp")),
        "ocr": (fps.get("frames"), OCR_VERSION),
        "slides": ([s.get("fp") for s in inp.get("slides", [])], fps.get("ocr")),
        "sources": (fps.get("transcribe"), fps.get("subtitle"), fps.get("ocr"), fps.get("slides"), job["mode"]),
        "material": (fps.get("sources"), job.get("title"), job.get("date"), job.get("note_lang"), opt.get("chunk_chars"),
                     courses.glossary(job.get("course_id")), (courses.get(job.get("course_id")) or {}).get("name")),
    }[stage]
    return fingerprint(stage, deps, (job.get("force") or {}).get(stage))   # force: 用户点了「重做这一步」

def _outputs_ok(job, stage):
    d = job_dir(job["id"]); w = os.path.join(d, "work")
    need = {"transcribe": [os.path.join(w, "lecture.srt")], "subtitle": [os.path.join(w, "lecture.srt")],
            "frames": [os.path.join(w, "frames")], "ocr": [], "slides": [os.path.join(w, "slides.json")],
            "sources": [os.path.join(d, "sources.json")], "material": [os.path.join(d, "ai", "material.md")]}.get(stage, [])
    return all(os.path.exists(p) for p in need)

# ---------------- 队列 ----------------

class Runner:
    def __init__(self):
        self.q = queue.Queue(); self.current = None; self.ctx = None; self.shutting_down = False
        self.t = threading.Thread(target=self._loop, daemon=True, name="lsk-runner"); self.t.start()

    def enqueue(self, jid):
        def fn(j):
            j["state"] = "queued"; j["current"] = None
        update(jid, fn); self.q.put(jid)

    def shutdown(self):
        """工作台退出时停掉正在运行的子进程(转写/抓帧),下次启动该任务会显示为「中断」"""
        self.shutting_down = True
        if self.ctx: self.ctx.cancelled = True; self.ctx.kill()

    def cancel(self, jid):
        if self.current == jid and self.ctx:
            self.ctx.cancelled = True; self.ctx.kill(); return True
        j = load(jid)
        if j and j["state"] == "queued":
            update(jid, lambda j: j.__setitem__("state", "cancelled")); return True
        return False

    def _loop(self):
        while True:
            jid = self.q.get()
            try:
                j = load(jid)
                if not j or j["state"] != "queued": continue
                self.current = jid
                self._run(jid)
            except Exception:
                traceback.print_exc()
            finally:
                self.current = None; self.ctx = None

    def _run(self, jid):
        update(jid, lambda j: (j.__setitem__("state", "running"), j.__setitem__("notices", [])))
        job = load(jid)
        fps = {}
        for stage in pipeline(job):
            job = load(jid)
            fp = stage_fp(job, stage, fps)
            st = job["stages"].get(stage, {})
            if st.get("status") == "done" and st.get("fp") == fp and _outputs_ok(job, stage):
                fps[stage] = fp; continue
            t0 = time.time()
            def start(j, stage=stage):
                j["current"] = stage
                j["stages"][stage] = {"status": "running", "started": now(), "fp": None, "progress": None}
            update(jid, start)
            self.ctx = ctx = Ctx(job, stage)
            try:
                HANDLERS[stage](load(jid), ctx)
            except Cancelled:
                _clean_partial(jid)
                if self.shutting_down:     # 工作台被关闭:标为中断,下次可以「继续」
                    self._finish(jid, stage, "interrupted", t0, {"what": "工作台在这一步进行中被关闭",
                                 "next": "点「继续」从这一步重新开始(之前完成的步骤不会重做)", "saved": "", "detail": ""})
                    update(jid, lambda j: j.__setitem__("state", "interrupted")); return
                self._finish(jid, stage, "cancelled", t0); update(jid, lambda j: j.__setitem__("state", "cancelled")); return
            except StageError as e:
                self._finish(jid, stage, "failed", t0, {"what": e.what, "next": e.next_step, "detail": e.detail}); return
            except Exception as e:
                tb = traceback.format_exc(); ctx.log(tb)
                self._finish(jid, stage, "failed", t0, {"what": f"程序内部错误:{type(e).__name__}: {e}",
                             "next": "点「重试」;如果重复出现,请导出诊断信息反馈", "detail": tb[-1500:]}); return
            fps[stage] = fp
            self._finish(jid, stage, "done", t0, fp=fp)
        update(jid, lambda j: (j.__setitem__("state", "done"), j.__setitem__("current", None)))

    def _finish(self, jid, stage, status, t0, error=None, fp=None):
        def fn(j):
            s = j["stages"].setdefault(stage, {})
            s.update({"status": status, "ended": now(), "elapsed": round(time.time() - t0, 1), "error": error, "fp": fp, "progress": None})
            if status == "failed":
                j["state"] = "failed"
                done = [STAGE_NAMES[k] for k, v in j["stages"].items() if v.get("status") == "done"]
                s["error"]["saved"] = ("已保存:" + "、".join(done) + "。重试时这些步骤不会重做。") if done else "还没有已完成的步骤。"
        update(jid, fn)

def _clean_partial(jid):
    """只清理本任务 work/ 下的半成品目录;原视频、已完成的结果和笔记都不在这里"""
    for p in (".partial-transcribe", ".partial-frames"):
        shutil.rmtree(os.path.join(job_dir(jid), "work", p), ignore_errors=True)

def recover_on_start():
    """程序重启:上次没跑完的任务标为"中断",界面上可以点「继续」"""
    n = 0
    for j in list_jobs():
        if j["state"] in ("running", "queued"):
            def fn(j):
                for k, s in j["stages"].items():
                    if s.get("status") == "running":
                        s.update({"status": "interrupted", "progress": None,
                                  "error": {"what": "程序在这一步进行中被关闭", "next": "点「继续」从这一步重新开始(之前完成的步骤不会重做)",
                                            "saved": "", "detail": ""}})
                j["state"] = "interrupted"
            update(j["id"], fn); n += 1
        _clean_partial(j["id"])
    return n
