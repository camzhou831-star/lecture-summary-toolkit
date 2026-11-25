"""FastAPI 后端。启动: cd workbench && uv run python -m wb   然后打开 http://127.0.0.1:8770"""
import json
import os
import shutil

import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, llm, pipeline, sources, templates, worker

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LANGS = {"auto", "zh", "en", "ja", "ko", "fr", "de", "es"}


@asynccontextmanager
async def lifespan(app):
    db.init()
    if os.environ.get("WORKBENCH_NO_WORKER") != "1":     # 测试里不起后台线程
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="总结工作台", lifespan=lifespan)


class NewTask(BaseModel):
    source: str
    lang: str = "auto"
    out_lang: str = "zh"
    template: str = "course"


def _check_template(t):
    if not templates.valid(t):
        raise HTTPException(400, f"不认识的模板 {t}")


def _check_langs(lang, out_lang):
    if lang not in LANGS:
        raise HTTPException(400, f"不支持的视频语言 {lang}")
    if out_lang not in ("zh", "en"):
        raise HTTPException(400, "总结语言只能是 zh 或 en")


def _public(t, full=False):
    d = {k: t[k] for k in ("id", "created_at", "updated_at", "kind", "source", "vid", "title", "lang", "out_lang", "template",
                           "status", "stage", "message", "timings", "check_ok", "meta")}
    if full:
        d["log"] = t["log"]
        d["check_report"] = t["check_report"]
    return d


@app.get("/api/config")
def get_config():
    c = config.llm_config()
    av = llm.available()
    try:
        active = llm.resolve()
    except llm.LLMError:
        active = None
    return {"model": c.model, "base_url": c.base_url, "key_ok": bool(c.api_key), "key_source": c.source,
            "provider": c.provider, "active": active, "ready": active is not None,
            "cookies_browser": config.cookies_browser(), "browsers": list(config.BROWSERS),
            "providers": [{"id": p, "name": info["name"], "ok": av[p][0], "note": av[p][1]} for p, info in llm.PROVIDERS.items()]}


class ProviderBody(BaseModel):
    provider: str


@app.post("/api/config/provider")
def set_provider(body: ProviderBody):
    if body.provider not in ("auto", *llm.PROVIDERS):
        raise HTTPException(400, "不认识的模型来源")
    config.save_provider(body.provider)
    return get_config()


class BrowserBody(BaseModel):
    browser: str = ""


@app.post("/api/config/cookies")
def set_cookies_browser(body: BrowserBody):
    if body.browser and body.browser not in config.BROWSERS:
        raise HTTPException(400, "不认识的浏览器")
    config.save_setting("cookies_browser", body.browser)
    return get_config()


class KeyBody(BaseModel):
    api_key: str = ""
    base_url: str = config.DEFAULT_BASE_URL
    model: str = config.DEFAULT_MODEL


@app.post("/api/config/key")
def set_key(body: KeyBody):
    """在界面里填 API Key(默认 DeepSeek)。先用 /models 试一下 Key 对不对,对了才存;空字符串 = 删掉 Key"""
    key, base = body.api_key.strip(), (body.base_url.strip() or config.DEFAULT_BASE_URL).rstrip("/")
    if key:
        if not base.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise HTTPException(400, "接口地址要以 https:// 开头")
        try:
            r = httpx.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        except httpx.HTTPError as e:
            raise HTTPException(400, f"连不上 {base}: {e}")
        if r.status_code in (401, 403):
            raise HTTPException(400, "Key 不对:接口说没有权限,检查一下有没有复制完整")
    config.save_setting("api_key", key)
    config.save_setting("base_url", base)
    config.save_setting("model", body.model.strip() or config.DEFAULT_MODEL)
    if key:
        config.save_provider("api")
    elif config.llm_config().provider == "api":
        config.save_provider("auto")
    return get_config()


@app.get("/api/templates")
def get_templates():
    return templates.listing()


@app.get("/api/status")
def get_status():
    """设置页:外部程序装没装、whisper 模型在不在、数据放在哪、任务数"""
    import sys
    sys.path.insert(0, config.TOOLS)
    import deps
    model = os.path.join(deps.MODEL_DIR, "ggml-" + os.environ.get("WHISPER_MODEL", "large-v3-turbo") + ".bin")
    tools = [{"name": n, "path": deps.find(n), "need": need} for n, need in
             (("yt-dlp", "B 站 / YouTube 链接"), ("ffmpeg", "转写前抽音频"), ("ffprobe", "读视频时长"), ("whisper-cli", "本地转写"))]
    tools.append({"name": "whisper 模型 " + os.path.basename(model), "path": model if os.path.isfile(model) else None, "need": "本地转写(第一次用时自动下载)"})
    counts = {}
    for t in db.list_all(limit=100000):
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {"tools": tools, "data_dir": config.DATA, "config_file": config.CONFIG_FILE, "counts": counts,
            "platform": sys.platform, "brew": bool(deps.find("brew")), "npm": bool(deps.find("npm")),
            "model_ready": os.path.isfile(model), "workbench_dir": config.WB_DIR}


@app.post("/api/tasks")
def create_task(body: NewTask):
    _check_langs(body.lang, body.out_lang)
    _check_template(body.template)
    try:
        kind, vid, source = sources.parse_source(body.source)
    except sources.SourceError as e:
        raise HTTPException(400, str(e))
    tid = db.create(kind, source, vid, lang=body.lang, out_lang=body.out_lang, template=body.template)
    worker.kick()
    return _public(db.get(tid))


@app.post("/api/upload")
def upload(file: UploadFile = File(...), lang: str = Form("auto"), out_lang: str = Form("zh"), template: str = Form("course")):
    _check_langs(lang, out_lang)
    _check_template(template)
    name = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(name)[1].lower()
    if ext not in sources.VIDEO_EXTS + sources.SUB_EXTS:
        raise HTTPException(400, f"不支持的文件类型 {ext}(支持视频、音频、.srt、.vtt)")
    up = os.path.join(config.DATA, "uploads")
    os.makedirs(up, exist_ok=True)
    dest = os.path.join(up, name)
    i = 1
    while os.path.exists(dest):
        stem, e = os.path.splitext(name)
        dest = os.path.join(up, f"{stem}-{i}{e}")
        i += 1
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f, 1 << 20)
    kind, vid, source = sources.parse_source(dest)
    tid = db.create(kind, source, vid, lang=lang, out_lang=out_lang, template=template)
    worker.kick()
    return _public(db.get(tid))


@app.get("/api/tasks")
def list_tasks():
    return [_public(t) for t in db.list_all()]


def _task(tid):
    t = db.get(tid)
    if not t:
        raise HTTPException(404, "没有这个任务")
    return t


@app.get("/api/tasks/{tid}")
def get_task(tid: int):
    return _public(_task(tid), full=True)


@app.get("/api/tasks/{tid}/summary", response_class=PlainTextResponse)
def get_summary(tid: int):
    p = pipeline.summary_path(_task(tid))
    if not os.path.exists(p):
        raise HTTPException(404, "总结还没生成")
    return open(p, encoding="utf-8").read()


@app.get("/api/tasks/{tid}/transcript", response_class=PlainTextResponse)
def get_transcript(tid: int):
    t = _task(tid)
    p = os.path.join(pipeline.task_root(tid), "课程视频", t["vid"] + ".srt")
    if not os.path.exists(p):
        raise HTTPException(404, "文字稿还没拿到")
    return open(p, encoding="utf-8").read()


@app.get("/api/tasks/{tid}/media")
def get_media(tid: int):
    """本地视频 / 音频(时间戳点了在页面里跳)。只给任务登记过的那个文件"""
    p = (_task(tid).get("meta") or {}).get("media_path")
    if not p or not os.path.isfile(p):
        raise HTTPException(404, "没有本地媒体文件")
    return FileResponse(p)


@app.post("/api/tasks/{tid}/retry")
def retry(tid: int):
    t = _task(tid)
    if t["status"] == "running":
        raise HTTPException(409, "任务正在跑")
    db.update(tid, status="queued", message="重新排队", check_ok=None, check_report=None)
    worker.kick()
    return _public(db.get(tid))


class DeriveBody(BaseModel):
    template: str
    out_lang: str = "zh"


@app.post("/api/tasks/{tid}/derive")
def derive(tid: int, body: DeriveBody):
    """换个用途:用这个任务已经拿到的文字稿,换一个模板 / 语言再出一份(新任务,原来那份保留),不用重新下载和转写"""
    t = _task(tid)
    _check_template(body.template)
    _check_langs(t["lang"], body.out_lang)
    src_root = pipeline.task_root(tid)
    srt = os.path.join(src_root, "课程视频", t["vid"] + ".srt")
    if not os.path.isfile(srt) or os.path.getsize(srt) == 0:
        raise HTTPException(400, "这个任务还没拿到文字稿,等它拿完再换用途")
    timings = {"fetch": t["timings"]["fetch"]} if t["timings"].get("fetch") is not None else {}
    nid = db.create(t["kind"], t["source"], t["vid"], lang=t["lang"], out_lang=body.out_lang, template=body.template, title=t["title"])
    dst_root = pipeline.task_root(nid)
    os.makedirs(os.path.join(dst_root, "课程视频"), exist_ok=True)
    for name in (t["vid"] + ".srt", t["vid"] + ".txt"):           # 只复制原始文字稿;讲义稿等按新模板重新整理
        p = os.path.join(src_root, "课程视频", name)
        if os.path.isfile(p):
            shutil.copyfile(p, os.path.join(dst_root, "课程视频", name))
    for name in ("meta.json", "来源.txt"):
        p = os.path.join(src_root, name)
        if os.path.isfile(p):
            shutil.copyfile(p, os.path.join(dst_root, name))
    meta = dict(t["meta"] or {}, derived_from=tid)
    with open(os.path.join(dst_root, "meta.json"), "w", encoding="utf-8") as f:   # 跑的时候 pipeline 从这里读视频信息
        json.dump(meta, f, ensure_ascii=False, indent=1)
    db.update(nid, meta=meta, timings=timings, message="排队中(沿用任务 %d 的文字稿)" % tid)
    worker.kick()
    return _public(db.get(nid))


@app.delete("/api/tasks/{tid}")
def delete_task(tid: int):
    t = _task(tid)
    if t["status"] == "running":
        raise HTTPException(409, "任务正在跑,等它结束再删")
    shutil.rmtree(pipeline.task_root(tid), ignore_errors=True)
    db.delete(tid)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})   # 改了前端刷新就生效


app.mount("/static", StaticFiles(directory=STATIC), name="static")
