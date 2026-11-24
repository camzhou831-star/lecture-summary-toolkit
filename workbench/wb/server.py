"""FastAPI 后端。启动: cd workbench && uv run python -m wb   然后打开 http://127.0.0.1:8770"""
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, pipeline, sources, worker

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
    return {"model": c.model, "base_url": c.base_url, "key_ok": bool(c.api_key), "key_source": c.source}


@app.post("/api/tasks")
def create_task(body: NewTask):
    _check_langs(body.lang, body.out_lang)
    try:
        kind, vid, source = sources.parse_source(body.source)
    except sources.SourceError as e:
        raise HTTPException(400, str(e))
    tid = db.create(kind, source, vid, lang=body.lang, out_lang=body.out_lang)
    worker.kick()
    return _public(db.get(tid))


@app.post("/api/upload")
def upload(file: UploadFile = File(...), lang: str = Form("auto"), out_lang: str = Form("zh")):
    _check_langs(lang, out_lang)
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
    tid = db.create(kind, source, vid, lang=lang, out_lang=out_lang)
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
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
