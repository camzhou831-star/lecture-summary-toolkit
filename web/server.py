"""本地网页工作台的 HTTP 服务(只用 Python 标准库)。
安全:只监听 127.0.0.1;Host 头校验(防 DNS rebinding);会话 cookie(HttpOnly + SameSite=Strict,从启动链接获得);
     POST 校验 Origin;文件只能访问任务自己登记过的文件;严格 CSP,页面不加载任何外部资源。"""
import html, json, mimetypes, os, re, secrets, shutil, subprocess, sys, threading, time, urllib.parse, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .util import (STATIC, TOOLS, VERSION, data_root, read_json, atomic_write_json, atomic_write_text, now, redact, which,
                   IS_MAC, IS_WINDOWS, hms)
from . import jobs, courses, sources, materials, checks, mdrender, exporter, pdftext, models
from . import templates as T

sys.path.insert(0, TOOLS)
import course_meta  # noqa: E402

EXT = {"video": {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".m4a", ".mp3", ".wav"},
       "cam": {".mp4", ".mkv", ".mov", ".webm", ".m4v"},
       "subtitle": {".srt", ".vtt"}, "slides": {".pdf"}, "summary": {".md", ".markdown", ".txt"}}
RUNNER = None
PORT = None
TOKEN = None

CSP = "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

class ApiError(Exception):
    def __init__(self, status, msg, next_step=""):
        super().__init__(msg); self.status, self.msg, self.next_step = status, msg, next_step

def _session_token():
    p = os.path.join(data_root(), "session.json")
    s = read_json(p) or {}
    if not s.get("token"):
        s = {"token": secrets.token_urlsafe(24), "created": now()}
        atomic_write_json(p, s)
        try: os.chmod(p, 0o600)
        except OSError: pass
    return s["token"]

# ---------------- 文件选择(系统对话框,只记录路径,不移动/复制原视频) ----------------

def native_pick(role):
    exts = sorted(EXT[role]); multiple = role == "slides"
    prompt = {"video": "选择录播视频(或音频)", "cam": "选择第二路录像(实物投影/手写)", "subtitle": "选择字幕文件(.srt / .vtt)",
              "slides": "选择课件 PDF(可多选)", "summary": "选择 AI 生成的笔记(.md)"}[role]
    if IS_MAC and which("osascript"):
        types = ", ".join(f'"{e[1:]}"' for e in exts)
        script = (f'set fs to choose file with prompt "{prompt}" of type {{{types}}}' + (" with multiple selections allowed" if multiple else "") + "\n"
                  'set out to ""\n'
                  + ('repeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\n' if multiple else 'set out to POSIX path of fs\n')
                  + 'return out')
        r = subprocess.run(["osascript", "-e", 'tell application "System Events" to activate', "-e", script], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            if "-128" in r.stderr: return []           # 用户点了取消
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                if "-128" in r.stderr: return []
                raise ApiError(500, "无法打开文件选择窗口", "可以把文件直接拖进网页里")
        return [l for l in r.stdout.splitlines() if l.strip()]
    if IS_WINDOWS:
        flt = ";".join("*" + e for e in exts)
        ps = ("Add-Type -AssemblyName System.Windows.Forms;$f=New-Object System.Windows.Forms.OpenFileDialog;"
              f"$f.Title='{prompt}';$f.Filter='{prompt}|{flt}';$f.Multiselect=${'true' if multiple else 'false'};"
              "if($f.ShowDialog() -eq 'OK'){[Console]::OutputEncoding=[Text.Encoding]::UTF8;$f.FileNames}")
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, timeout=600)
        return [l.strip() for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    raise ApiError(501, "这个系统上不支持打开文件选择窗口", "请把文件拖进网页里")

def _check_ext(role, name):
    ext = os.path.splitext(name)[1].lower()
    if ext not in EXT[role]:
        want = "、".join(sorted(EXT[role]))
        raise ApiError(400, f"「{name}」不是支持的文件类型", f"这里需要 {want} 文件")

def _guess_from_name(job, name):
    """用文件名猜课程与日期(识别不了也没关系)"""
    meta = course_meta.parse(name, {})
    changes = {}
    if not job.get("title"): changes["title"] = os.path.splitext(os.path.basename(name))[0]
    if meta:
        if meta.get("date") and not job.get("date"): changes["date"] = meta["date"]
        if not job.get("course_id"):
            cid = courses.find_by_code(meta.get("unit"))
            if cid: changes["course_id"] = cid
            else: changes["_suggest_code"] = meta.get("unit")
    return changes

def set_input(jid, role, path):
    _check_ext(role, path)
    if not os.path.isfile(path): raise ApiError(400, f"找不到文件:{os.path.basename(path)}")
    d = jobs.describe_input(path)
    job = jobs.load(jid)
    if job["state"] in ("running", "queued"): raise ApiError(409, "任务正在处理,不能修改材料", "先点「取消」再修改")
    relocate = None
    old = job["inputs"].get(role) if role != "slides" else None
    if old:
        relocate = ("same" if old.get("fp") == d["fp"] else "different")
    guess = _guess_from_name(job, path) if not (role != "slides" and job["inputs"].get(role)) else {}   # 重新定位时不改标题/日期
    suggest = guess.pop("_suggest_code", None)
    def fn(j):
        if role == "slides":
            if not any(s["fp"] == d["fp"] for s in j["inputs"]["slides"]): j["inputs"]["slides"].append(d)
        else: j["inputs"][role] = d
        for k, v in guess.items(): j[k] = v
        if j["state"] in ("done", "failed", "cancelled", "interrupted"): j["state"] = "draft"
    job = jobs.update(jid, fn)
    msg = {"same": "已重新定位:内容和之前的文件一致,已完成的步骤可以继续使用",
           "different": "注意:新选的文件和之前的内容不同,相关步骤会在下次处理时重做"}.get(relocate)
    return {"job": job, "suggest_code": suggest, "relocate": relocate, "message": msg}

# ---------------- 视图 ----------------

def mode_support():
    """按输入模式检查依赖(网页服务本身只需要 Python;处理流程另需外部工具)"""
    miss = lambda ts: [t for t in ts if not which(t)]
    pdf = pdftext.backend()
    video_missing = [] if not IS_WINDOWS else ["Windows 暂不支持视频处理"]
    video_missing += miss(["bash", "ffmpeg", "ffprobe", "whisper-cli", "tesseract"]) if not IS_WINDOWS else []
    try:
        import PIL  # noqa: F401
    except ImportError:
        video_missing.append("Python 图像库 Pillow")
    return {
        "video": {"ok": not video_missing, "missing": video_missing,
                  "hint": "Mac 终端运行:brew install ffmpeg whisper-cpp tesseract poppler" if video_missing and not IS_WINDOWS else "",
                  "model": models.present(models.DEFAULT_MODEL)},
        "subtitle": {"ok": True, "missing": [], "hint": "" if pdf else "没有 PDF 文字提取工具,课件不能用(brew install poppler 或 pip install pypdf)"},
        "slides": {"ok": bool(pdf), "missing": [] if pdf else ["pdftotext 或 pypdf"],
                   "hint": "" if pdf else "Mac:brew install poppler;其它系统:python -m pip install -r requirements-web.txt"},
    }

def job_view(job):
    jd = jobs.job_dir(job["id"])
    view = dict(job)
    view["pipeline"] = [{"key": s, "name": jobs.STAGE_NAMES[s], **(job["stages"].get(s) or {"status": "pending"})} for s in jobs.pipeline(job)]
    view["template_name"] = T.TEMPLATE_NAMES.get(job["template"])
    view["sections"] = T.section_titles(job["template"], job["mode"])
    for k in ("video", "cam", "subtitle"):
        if job["inputs"].get(k): view["inputs"][k] = dict(job["inputs"][k], exists=os.path.exists(job["inputs"][k]["path"]))
    view["course"] = courses.get(job.get("course_id"))
    view["has_material"] = os.path.exists(os.path.join(jd, "ai", "material.md"))
    return view

def _reg(jid):
    return sources.load(jobs.job_dir(jid))

CHECK_RULES = "checks-v2"

def _reg_for(job, ent=None):
    """某个笔记版本对应的来源表:导入时材料的快照;旧任务没有快照时用当前来源表"""
    fp = (ent or {}).get("material_fp") or (job.get("material") or {}).get("fp")
    if fp:
        snap = read_json(os.path.join(jobs.job_dir(job["id"]), "ai", f"sources-{fp}.json"))
        if snap: return snap
    return _reg(job["id"])

def _version(job, v=None):
    vers = job["ai"].get("versions") or []
    if not vers: return None
    return next((x for x in vers if x["v"] == v), None) if v else vers[-1]

def summary_payload(job, v=None):
    vers = job["ai"].get("versions") or []
    ent = _version(job, v)
    if not ent: return None
    text = open(os.path.join(jobs.job_dir(job["id"]), "ai", ent["file"]), encoding="utf-8").read()
    reg = _reg_for(job, ent)
    # 按这个版本导入时的档位与模式检查,不因为之后切换档位而改变旧版本的结论
    issues = checks.check_summary(text, reg, ent.get("template") or job["template"], ent.get("mode") or job["mode"], job["id"])
    cur_fp = (job.get("material") or {}).get("fp")
    stale = bool(ent.get("material_fp") and cur_fp and ent["material_fp"] != cur_fp)
    return {"version": ent, "versions": vers, "text": text, "html": mdrender.render(text, sources.index(reg)), "issues": issues,
            "stale_material": stale, "template_name": T.TEMPLATE_NAMES.get(ent.get("template") or job["template"])}

def evidence(job, sid, v=None):
    reg = _reg_for(job, _version(job, v)) if v else _reg_for(job); idx = sources.index(reg)
    s = idx.get(sid)
    if not s: raise ApiError(404, f"来源 {sid} 不存在", "这个编号可能是 AI 编造的")
    has_video = bool(job["inputs"].get("video")) and os.path.exists(job["inputs"]["video"]["path"])
    out = {"id": sid, "kind": s["kind"], "label": sources.label(s), "text": "", "image": None, "video": None, "t": sources.time_of(s)}
    if s["kind"] == "S":
        segs = reg["segments"]; i = next(k for k, x in enumerate(segs) if x["id"] == sid)
        out["text"] = s["text"]
        out["context"] = [{"id": x["id"], "label": hms(x["start"]), "text": x["text"]} for x in segs[max(0, i-1):i+2] if x["id"] != sid]
        out["range"] = f"{hms(s['start'])}–{hms(s['end'])}"
    elif s["kind"] == "P":
        out["text"] = s["text"]; out["image"] = f"/files/{job['id']}/page/{s['deck_idx']}/{s['page']}"
        out["label"] = f"{s['deck']} · PDF 第 {s['page']} 页"
    elif s["kind"] == "F":
        out["text"] = s.get("text") or ""; out["image"] = f"/files/{job['id']}/frame/{urllib.parse.quote(s['file'])}"
        out["slide"] = s.get("slide")
        if s.get("slide") and s["slide"] in idx: out["slide_label"] = sources.label(idx[s["slide"]])
    elif s["kind"] == "H":
        out["image"] = f"/files/{job['id']}/frame/{urllib.parse.quote(s['file'])}"; out["text"] = "手写页没有文字识别,请看图"
    if has_video and out["t"] is not None: out["video"] = f"/files/{job['id']}/video"
    return out

def diagnostics(job):
    """不含课程正文、密钥;路径脱敏"""
    d = {"tool_version": VERSION, "platform": sys.platform, "python": sys.version.split()[0], "generated": now(),
         "tools": {t: bool(which(t)) for t in ("bash", "ffmpeg", "ffprobe", "whisper-cli", "tesseract", "pdftotext", "pdftoppm")},
         "job": {"id": job["id"], "mode": job["mode"], "template": job["template"], "state": job["state"], "options": job["options"],
                 "inputs": {k: ({"ext": os.path.splitext(v["name"])[1], "size": v["size"]} if isinstance(v, dict) else
                                [{"ext": os.path.splitext(x["name"])[1], "size": x["size"]} for x in v] if isinstance(v, list) else None)
                            for k, v in job["inputs"].items()},
                 "stages": {k: {"status": v.get("status"), "elapsed": v.get("elapsed"),
                                "error": {"what": redact((v.get("error") or {}).get("what")), "detail": redact((v.get("error") or {}).get("detail"))} if v.get("error") else None}
                            for k, v in job["stages"].items()},
                 "info": {k: v for k, v in (job.get("info") or {}).items() if k in ("duration", "n_segments", "n_frames", "n_cam", "n_pages", "subtitle_format")},
                 "ai_versions": len(job["ai"].get("versions") or [])}}
    return d

# ---------------- HTTP ----------------

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)): return   # 浏览器中途断开(拖动视频进度条时很常见)
        super().handle_error(request, client_address)

class Handler(BaseHTTPRequestHandler):
    server_version = "LSK/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("LSK_DEBUG"): sys.stderr.write("%s\n" % (fmt % args))

    # ---- 基础 ----
    def _host_ok(self):
        h = (self.headers.get("Host") or "").lower()
        return h in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "lsk_s": return v
        return None

    def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer"); self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000_000: raise ApiError(413, "内容太大")
        raw = self.rfile.read(n) if n else b"{}"
        try: return json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError): raise ApiError(400, "请求格式不对")

    def _gate(self, need_session=True):
        if not self._host_ok():
            self._send(403, "forbidden", "text/plain"); return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
                self._send(403, {"error": "来源不对"}); return False
        if need_session and not (self._cookie() and secrets.compare_digest(self._cookie(), TOKEN)):
            if self.path.startswith("/api/") or self.path.startswith("/files/"):
                self._send(401, {"error": "会话已失效", "next": "关掉这个页面,从「启动工作台」重新打开"})
            else:
                self._send(401, NOT_AUTHED, "text/html; charset=utf-8")
            return False
        return True

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); path = u.path; qs = urllib.parse.parse_qs(u.query)
        if path == "/auth":
            if not self._host_ok(): return self._send(403, "forbidden", "text/plain")
            t = (qs.get("t") or [""])[0]
            if not secrets.compare_digest(t, TOKEN): return self._send(401, NOT_AUTHED, "text/html; charset=utf-8")
            self.send_response(303)
            self.send_header("Set-Cookie", f"lsk_s={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/"); self.send_header("Content-Length", "0"); self.end_headers(); return
        if not self._gate(): return
        try:
            if path == "/" or path == "/index.html": return self._static("index.html")
            if path.startswith("/static/"): return self._static(path[len("/static/"):])
            if path.startswith("/files/"): return self._files(path)
            if path.startswith("/api/"): return self._api("GET", path, qs, None)
            self._send(404, {"error": "not found"})
        except ApiError as e:
            self._send(e.status, {"error": e.msg, "next": e.next_step})
        except (KeyError, FileNotFoundError):
            self._send(404, {"error": "找不到这个任务或文件"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._internal(e)

    def do_POST(self):
        if not self._gate(): return
        u = urllib.parse.urlsplit(self.path); qs = urllib.parse.parse_qs(u.query)
        try:
            if re.fullmatch(r"/api/jobs/[^/]+/upload", u.path): return self._upload(u.path.split("/")[3], qs)
            body = self._json_body()
            return self._api("POST", u.path, qs, body)
        except ApiError as e:
            self._send(e.status, {"error": e.msg, "next": e.next_step})
        except KeyError:
            self._send(404, {"error": "找不到这个任务"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._internal(e)

    def _internal(self, e):
        import traceback
        traceback.print_exc()
        try: self._send(500, {"error": f"工作台内部错误:{type(e).__name__}", "next": "刷新页面重试;重复出现请导出诊断信息反馈"})
        except Exception: pass

    def _static(self, name):
        p = os.path.realpath(os.path.join(STATIC, name))
        if not p.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(p): return self._send(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml"}.get(os.path.splitext(p)[1], "application/octet-stream")
        self._send(200, open(p, "rb").read(), ctype)

    def _files(self, path):
        parts = [urllib.parse.unquote(x) for x in path.split("/")[2:]]
        jid, kind = parts[0], parts[1]
        job = jobs.load(jid)
        if not job: raise KeyError(jid)
        jd = jobs.job_dir(jid)
        if kind == "frame":
            rel = "/".join(parts[2:])
            if not re.fullmatch(r"(cam/)?t\d{5}s(-\d+)?\.jpg", rel): raise ApiError(400, "非法文件名")
            p = os.path.join(jd, "work", "frames", rel)
            if not os.path.isfile(p): raise ApiError(404, "截图不存在(可能在重新处理画面时被替换了)")
            return self._send(200, open(p, "rb").read(), "image/jpeg", {"Cache-Control": "private, max-age=300"})
        if kind == "page":
            di, pg = int(parts[2]), int(parts[3])
            reg = _reg(jid); deck = next((d for d in reg["decks"] if d["idx"] == di), None)
            if not deck or not (1 <= pg <= len(deck["pages"])): raise ApiError(404, "课件页不存在")
            png = os.path.join(jd, "work", "pages", f"{di}-{pg}.png")
            if not pdftext.render_page(deck["file"], pg, png):
                raise ApiError(404, "无法显示课件页图片(需要 poppler 的 pdftoppm),只能看文字")
            return self._send(200, open(png, "rb").read(), "image/png", {"Cache-Control": "private, max-age=300"})
        if kind == "video":
            v = (job["inputs"].get("video") or {}).get("path")
            if not v or not os.path.isfile(v): raise ApiError(404, "找不到视频文件")
            return self._range(v)
        raise ApiError(404, "not found")

    def _range(self, p):
        """单段 Range:bytes=a-b / a- / -n。语法不对或多段 → 按规范忽略,返回整个文件;起点超出文件 → 416"""
        size = os.path.getsize(p)
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        rng = (self.headers.get("Range") or "").strip()
        start, end, status = 0, size - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1)); end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                if m.group(2) and int(m.group(2)) < start: start, end = 0, size - 1   # 无效区间:忽略 Range
                elif start >= size:
                    self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.send_header("Content-Length", "0"); self.end_headers(); return
                else: status = 206
            else:
                n = int(m.group(2))
                if n == 0:
                    self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.send_header("Content-Length", "0"); self.end_headers(); return
                start = max(0, size - n); status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(length))
        if status == 206: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Security-Policy", CSP); self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD": return
        with open(p, "rb") as f:
            f.seek(start); left = length
            while left > 0:
                buf = f.read(min(1 << 20, left))
                if not buf: break
                self.wfile.write(buf); left -= len(buf)

    def _upload(self, jid, qs):
        role = (qs.get("role") or [""])[0]; name = os.path.basename((qs.get("name") or [""])[0])
        if role not in EXT: raise ApiError(400, "未知的材料类型")
        _check_ext(role, name)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0: raise ApiError(400, "文件是空的")
        job = jobs.load(jid)
        if not job: raise KeyError(jid)
        jd = jobs.job_dir(jid)
        free = shutil.disk_usage(jd).free
        if n + 200_000_000 > free: raise ApiError(507, f"磁盘空间不够保存这个文件({n/1e9:.1f} GB)")
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip() or "file"
        dest = os.path.join(jd, "inputs", safe)
        base, ext = os.path.splitext(dest); k = 2
        while os.path.exists(dest): dest = f"{base}-{k}{ext}"; k += 1
        tmp = dest + ".uploading"
        left = n
        with open(tmp, "wb") as f:
            while left > 0:
                buf = self.rfile.read(min(1 << 20, left))
                if not buf: break
                f.write(buf); left -= len(buf)
        if left:
            os.remove(tmp); raise ApiError(400, "上传中断,文件不完整", "重新拖入文件")
        os.replace(tmp, dest)
        if role == "summary":
            return self._send(200, {"text": open(dest, encoding="utf-8", errors="replace").read()})
        res = set_input(jid, role, dest); res["job"] = job_view(res["job"])
        return self._send(200, res)

    # ---- API ----
    def _api(self, method, path, qs, body):
        p = path.split("/")[2:]   # ["jobs", id, ...]
        if method == "GET" and p == ["state"]:
            return self._send(200, {
                "version": VERSION, "platform": "mac" if IS_MAC else "windows" if IS_WINDOWS else sys.platform,
                "tools": {t: bool(which(t)) for t in ("ffmpeg", "whisper-cli", "tesseract", "pdftotext", "pdftoppm")},
                "pdf_backend": pdftext.backend(), "model_present": models.present(models.DEFAULT_MODEL), "modes": mode_support(),
                "courses": courses.all_courses(),
                "jobs": [{k: j.get(k) for k in ("id", "title", "mode", "state", "created", "updated", "current", "course_id", "date")} for j in jobs.list_jobs()],
                "running": RUNNER.current, "data_dir": redact(data_root())})
        if p == ["courses"] and method == "POST":
            cid, c = courses.upsert(body.get("id"), body)
            return self._send(200, {"id": cid, "course": c})
        if p == ["jobs"] and method == "POST":
            mode = body.get("mode")
            if mode not in T.MODE_NAMES: raise ApiError(400, "请选择材料类型")
            c = courses.get(body.get("course_id")) or {}
            job = jobs.create({"mode": mode, "title": body.get("title"), "course_id": body.get("course_id"),
                               "template": body.get("template") or c.get("template") or "full",
                               "lang": c.get("lang") or "en", "note_lang": c.get("note_lang") or "zh"})
            if IS_WINDOWS: jobs.update(job["id"], lambda j: j["options"].__setitem__("frames", False))
            return self._send(200, job_view(jobs.load(job["id"])))
        if not p or p[0] != "jobs" or len(p) < 2: raise ApiError(404, "not found")
        jid = p[1]; job = jobs.load(jid)
        if not job: raise KeyError(jid)
        jd = jobs.job_dir(jid); sub = p[2:]

        if method == "GET" and not sub:
            v = job_view(job)
            if job.get("material"): v["prompt_preview"] = None
            return self._send(200, v)
        if method == "POST" and sub == ["meta"]:
            def fn(j):
                for k in ("title", "date", "course_id", "template", "lang", "note_lang"):
                    if k in body and body[k] is not None: j[k] = body[k]
                for k in ("frames", "frame_mode", "whisper_model", "vad", "chunk_chars"):
                    if k in (body.get("options") or {}): j["options"][k] = body["options"][k]
            if job["state"] in ("running", "queued") and set(body) - {"title", "date", "template", "note_lang"}:
                raise ApiError(409, "任务正在处理,不能修改这些设置", "先点「取消」")
            if body.get("options", {}).get("frame_mode") and not re.fullmatch(r"[1-9]\d?s|0?\.\d+", body["options"]["frame_mode"]):
                raise ApiError(400, "抓帧间隔格式不对(例如 12s)")
            return self._send(200, job_view(jobs.update(jid, fn)))
        if method == "POST" and sub == ["pick"]:
            role = body.get("role")
            if role not in EXT: raise ApiError(400, "未知的材料类型")
            paths = native_pick(role)
            if not paths: return self._send(200, {"cancelled": True, "job": job_view(job)})
            if role == "summary":
                return self._send(200, {"text": open(paths[0], encoding="utf-8", errors="replace").read()})
            res = None
            for pth in paths: res = set_input(jid, role, pth)
            res["job"] = job_view(res["job"]); return self._send(200, res)
        if method == "POST" and sub == ["path"]:
            # 手动输入路径(没有系统文件对话框时 / 高级用户);同样只记录位置,不移动文件
            role, pth = body.get("role"), os.path.expanduser((body.get("path") or "").strip().strip('"').strip("'"))
            if role not in ("video", "cam", "subtitle", "slides"): raise ApiError(400, "未知的材料类型")
            res = set_input(jid, role, pth); res["job"] = job_view(res["job"]); return self._send(200, res)
        if method == "POST" and sub == ["remove"]:
            role = body.get("role")
            def fn(j):
                if role == "slides":
                    i = int(body.get("index", -1))
                    if 0 <= i < len(j["inputs"]["slides"]): j["inputs"]["slides"].pop(i)
                elif role in ("video", "cam", "subtitle"): j["inputs"][role] = None
                if j["state"] in ("done", "failed", "cancelled", "interrupted"): j["state"] = "draft"
            if job["state"] in ("running", "queued"): raise ApiError(409, "任务正在处理,不能修改材料", "先点「取消」")
            return self._send(200, job_view(jobs.update(jid, fn)))
        if method == "POST" and sub == ["start"]:
            if job["state"] in ("running", "queued"): raise ApiError(409, "任务已经在处理了")
            inp = job["inputs"]
            if job["mode"] == "video" and not inp.get("video"): raise ApiError(400, "还没有选择录播视频", "点「选择视频」")
            if job["mode"] == "subtitle" and not inp.get("subtitle"): raise ApiError(400, "还没有选择字幕文件", "点「选择字幕」")
            if job["mode"] == "slides" and not inp.get("slides"): raise ApiError(400, "还没有添加课件 PDF", "点「添加课件」")
            for k in ("video", "cam", "subtitle"):
                if inp.get(k) and not os.path.exists(inp[k]["path"]):
                    raise ApiError(400, f"找不到之前选的文件:{inp[k]['name']}", "点「重新选择」指定文件的新位置")
            # 文件在上次之后被修改过:更新指纹,相关步骤会自动重做
            def refresh(j):
                for k in ("video", "cam", "subtitle"):
                    if j["inputs"].get(k): j["inputs"][k] = jobs.describe_input(j["inputs"][k]["path"])
                j["inputs"]["slides"] = [jobs.describe_input(s["path"]) for s in j["inputs"]["slides"] if os.path.exists(s["path"])]
            jobs.update(jid, refresh)
            try: RUNNER.enqueue(jid)
            except jobs.AlreadyQueued: raise ApiError(409, "任务已经在处理了")
            return self._send(200, job_view(jobs.load(jid)))
        if method == "POST" and sub == ["cancel"]:
            ok = RUNNER.cancel(jid)
            return self._send(200, {"ok": ok, "job": job_view(jobs.load(jid))})
        if method == "POST" and sub == ["redo"]:
            st = body.get("stage")
            if st not in jobs.HANDLERS: raise ApiError(400, "未知步骤")
            jobs.update(jid, lambda j: j.setdefault("force", {}).__setitem__(st, now()))
            return self._send(200, job_view(jobs.load(jid)))
        if method == "POST" and sub == ["delete"]:
            # 只删工作台里这个任务的文件夹;原视频、原字幕、原课件在别处,不会被删
            if not jobs.delete(jid): raise ApiError(409, "任务正在处理", "先取消")
            return self._send(200, {"ok": True})
        if method == "GET" and sub == ["material"]:
            kind = (qs.get("kind") or ["full"])[0]
            if kind == "full": fn = "material.md"
            else: fn = f"chunk-{int((qs.get('no') or ['1'])[0])}.md"
            fp = os.path.join(jd, "ai", fn)
            if not os.path.exists(fp): raise ApiError(404, "AI 材料还没有生成", "先完成预处理")
            text = open(fp, encoding="utf-8").read()
            if (qs.get("download") or ["0"])[0] == "1":
                name = f"AI材料-{jid}.md" if kind == "full" else f"AI材料-{jid}-第{fn[6:-3]}块.md"
                return self._send(200, text, "text/markdown; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})
            return self._send(200, {"text": text})
        if method == "GET" and sub == ["prompt"]:
            kind = (qs.get("kind") or ["upload"])[0]
            meta = jobs.material_meta(job)
            if kind == "upload": t = materials.prompt_upload(meta, job["mode"], job["template"])
            elif kind == "paste":
                t = materials.prompt_single_paste(meta, job["mode"], job["template"]) + "\n\n" + open(os.path.join(jd, "ai", "material.md"), encoding="utf-8").read()
            elif kind == "chunk":
                k = int((qs.get("no") or ["1"])[0]); n = job["ai"].get("parts_n") or 1
                t = materials.prompt_chunk(meta, job["mode"], k, n) + "\n\n" + open(os.path.join(jd, "ai", f"chunk-{k}.md"), encoding="utf-8").read()
            elif kind == "merge":
                n = job["ai"].get("parts_n") or 0
                st = checks.parts_status(job["ai"].get("parts") or {}, n)
                if st: raise ApiError(400, st[0]["msg"], st[0]["fix"])
                t = materials.prompt_merge(meta, job["mode"], job["template"], [job["ai"]["parts"][str(k)] for k in range(1, n + 1)])
            else: raise ApiError(400, "未知类型")
            return self._send(200, {"text": t, "chars": len(t)})
        if method == "POST" and len(sub) == 2 and sub[0] == "parts":
            k = int(sub[1]); n = job["ai"].get("parts_n") or 0
            if not (1 <= k <= n): raise ApiError(400, "分块编号不对")
            text = body.get("text") or ""
            atomic_write_text(os.path.join(jd, "ai", f"part-{k}.md"), text)
            jobs.update(jid, lambda j: j["ai"]["parts"].__setitem__(str(k), text))
            iss = checks.check_part(text, k, n, _reg(jid), job["mode"], jid) if text.strip() else []
            job = jobs.load(jid)
            return self._send(200, {"issues": iss, "overall": checks.parts_status(job["ai"]["parts"], n)})
        if method == "GET" and sub == ["parts"]:
            n = job["ai"].get("parts_n") or 0; parts = job["ai"].get("parts") or {}
            res = {str(k): checks.check_part(parts[str(k)], k, n, _reg(jid), job["mode"], jid) for k in range(1, n + 1) if (parts.get(str(k)) or "").strip()}
            return self._send(200, {"n": n, "parts": parts, "issues": res, "overall": checks.parts_status(parts, n)})
        if method == "POST" and sub == ["summary"]:
            text = body.get("text") or ""
            if not text.strip(): raise ApiError(400, "内容是空的", "把 AI 的回复粘贴进来")
            vers = job["ai"].get("versions") or []
            v = (vers[-1]["v"] + 1) if vers else 1
            fn = f"summary-v{v}.md"
            atomic_write_text(os.path.join(jd, "ai", fn), text)
            iss = checks.check_summary(text, _reg_for(job), job["template"], job["mode"], jid)
            ent = {"v": v, "file": fn, "created": now(), "source": body.get("source") or "paste",
                   "template": job["template"], "mode": job["mode"], "note_lang": job.get("note_lang"),
                   "material_fp": (job.get("material") or {}).get("fp"), "rules": CHECK_RULES,
                   "errors": sum(1 for i in iss if i["level"] == "error"), "warnings": sum(1 for i in iss if i["level"] == "warn")}
            job = jobs.update(jid, lambda j: j["ai"].setdefault("versions", []).append(ent))
            return self._send(200, summary_payload(job, v))
        if method == "GET" and sub == ["summary"]:
            v = int((qs.get("v") or ["0"])[0]) or None
            pl = summary_payload(job, v)
            return self._send(200, pl or {"versions": []})
        if method == "GET" and len(sub) == 2 and sub[0] == "source":
            return self._send(200, evidence(job, sub[1], int((qs.get("v") or ["0"])[0]) or None))
        if method == "GET" and sub == ["export"]:
            fmt = (qs.get("fmt") or ["md"])[0]; v = int((qs.get("v") or ["0"])[0]) or None
            pl = summary_payload(job, v)
            if not pl: raise ApiError(404, "还没有导入笔记")
            idx = sources.index(_reg_for(job, pl["version"]))
            title = job.get("title") or jid
            safe = re.sub(r'[\\/:*?"<>|]', "_", title)
            if fmt == "html":
                body_ = exporter.to_html(pl["text"], idx, title); ctype = "text/html; charset=utf-8"; name = safe + ".html"
            else:
                vid = (job["inputs"].get("video") or {}).get("path")
                body_ = exporter.to_markdown(pl["text"], idx, obsidian=(fmt == "obsidian"), video_path=vid,
                                             frames_dir=os.path.join(jd, "work", "frames"))
                ctype = "text/markdown; charset=utf-8"; name = safe + (".obsidian" if fmt == "obsidian" else "") + ".md"
            return self._send(200, body_, ctype, {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})
        if method == "GET" and sub == ["diagnostics"]:
            return self._send(200, json.dumps(diagnostics(job), ensure_ascii=False, indent=1), "application/json; charset=utf-8",
                              {"Content-Disposition": f"attachment; filename=diagnostics-{jid}.json"})
        if method == "GET" and sub == ["log"]:
            st = (qs.get("stage") or [""])[0]
            if st not in jobs.HANDLERS: raise ApiError(400, "未知步骤")
            lp = os.path.join(jd, "logs", st + ".log")
            return self._send(200, {"text": open(lp, encoding="utf-8", errors="replace").read()[-6000:] if os.path.exists(lp) else ""})
        if method == "POST" and sub == ["glossary"]:
            cid = job.get("course_id")
            if not cid: raise ApiError(400, "这个任务还没有选课程,术语表要保存在课程里", "先选择或新建课程")
            terms = courses.glossary(cid)
            for t in body.get("add") or []:
                if t not in terms: terms.append(t)
            terms = [t for t in terms if t not in (body.get("remove") or [])]
            courses.upsert(cid, {"glossary": terms})
            return self._send(200, job_view(jobs.load(jid)))
        raise ApiError(404, "not found")

NOT_AUTHED = """<!doctype html><meta charset="utf-8"><title>课程笔记工作台</title>
<body style="font:16px/1.7 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:560px;margin:80px auto;padding:0 16px">
<h2>请从启动程序打开工作台</h2><p>为了防止其它网页访问你的课程资料,工作台只接受从「启动工作台」打开的链接。</p>
<p>请关掉这个页面,重新双击 <b>启动工作台</b>;如果它已经在运行,在它的窗口里找到以 <code>http://127.0.0.1</code> 开头的链接打开。</p></body>"""

def main(argv=None):
    global RUNNER, PORT, TOKEN
    import argparse, socket
    ap = argparse.ArgumentParser(description="课程笔记本地工作台")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LSK_PORT", "8765")))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    TOKEN = _session_token()
    n = jobs.recover_on_start()
    httpd = None
    for port in [a.port] + list(range(a.port + 1, a.port + 20)):
        try:
            httpd = Server(("127.0.0.1", port), Handler); PORT = port; break
        except OSError:
            continue
    if not httpd: sys.exit("错误: 找不到可用端口")
    httpd.daemon_threads = True
    RUNNER = jobs.Runner()
    url = f"http://127.0.0.1:{PORT}/auth?t={TOKEN}"
    print("=" * 60)
    print(" 课程笔记工作台已启动")
    print(f" 在浏览器打开: {url}")
    print(" 关闭浏览器后,正在处理的任务会继续;关闭这个窗口(或按 Ctrl+C)会停止工作台,")
    print(" 正在进行的那一步会中断,下次启动后可以点「继续」,已完成的步骤不会重做。")
    if n: print(f" 上次有 {n} 个任务没有完成,已标为「中断」。")
    print(f" 数据保存在: {data_root()}")
    print("=" * 60, flush=True)
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    import signal
    def _stop(signum, frame):
        raise KeyboardInterrupt
    for sig in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, sig): signal.signal(getattr(signal, sig), _stop)   # 关闭终端窗口时收到 SIGHUP
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cur = RUNNER.current
        RUNNER.shutdown()
        if cur:
            for _ in range(20):            # 等后台线程把任务标成「中断」
                if RUNNER.current is None: break
                time.sleep(0.2)
        print("\n工作台已停止。" + ("正在处理的任务已中断,下次启动后可以点「继续」。" if cur else ""))
