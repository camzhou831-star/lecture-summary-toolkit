"""来源登记表:把转写、课件页、截图、手写帧编成稳定的编号,AI 只引用编号,链接和时间由程序生成。
  S12   第 12 段转写(按分钟合并,记录真实的起止秒)
  P2-5  第 2 份课件 PDF 的第 5 页(PDF 页序,不是印刷页码)
  F7    第 7 张截图(录播画面)
  H3    第 3 张手写页(实物投影那一路)
"""
import json, os, re, sys
from .util import TOOLS, atomic_write_json, read_json, hms
from . import subtitles

sys.path.insert(0, TOOLS)
import compact as _compact  # noqa: E402

ID_RE = re.compile(r"\[((?:S\d+|P\d+-\d+|F\d+|H\d+)(?:\s*[,，、]\s*(?:S\d+|P\d+-\d+|F\d+|H\d+))*)\]")
ONE_ID = re.compile(r"S\d+|P\d+-\d+|F\d+|H\d+")

def segments_from_srt(srt_path):
    """按分钟合并转写(过滤幻觉与复读,规则与 compact.py 相同),每段保留真实起止时间"""
    cues, _ = subtitles.parse(subtitles.load_file(srt_path))
    cues = [c for c in cues if c.get("start") is not None]
    cues.sort(key=lambda c: c["start"])
    by_min, prev = {}, None
    for c in cues:
        n = _compact.norm(c["text"])
        if _compact.is_junk(n) or n == prev: continue
        prev = n
        by_min.setdefault(int(c["start"]) // 60, []).append(c)
    segs = []
    for i, mi in enumerate(sorted(by_min), 1):
        cs = by_min[mi]
        segs.append({"id": f"S{i}", "start": round(cs[0]["start"], 2), "end": round(max(c["end"] for c in cs), 2),
                     "text": " ".join(c["text"] for c in cs)})
    return segs

def silence_gaps(segs, min_gap=180):
    gaps = []
    for a, b in zip(segs, segs[1:]):
        # 与 build_bundle 相同:VAD 会把静音前一段的结束拉长,长而稀疏的段按 start+3 秒算
        dur = a["end"] - a["start"]
        end = a["start"] + 3 if dur >= 60 and len(a["text"].split()) / dur < 0.5 else a["end"]
        if b["start"] - end >= min_gap: gaps.append({"start": round(end, 1), "end": b["start"]})
    return gaps

def build(job_dir, mode, decks, has_video, duration=None):
    """decks: [{"file": 原始路径, "name": 显示名, "pages": [文字...], "status": ok/partial/none}]"""
    work = os.path.join(job_dir, "work")
    reg = {"mode": mode, "has_video": has_video, "duration": duration, "segments": [], "gaps": [],
           "decks": [], "frames": [], "cam": []}
    for di, d in enumerate(decks, 1):
        reg["decks"].append({"idx": di, "name": d["name"], "file": d["file"], "status": d.get("status", "ok"),
                             "pages": [{"id": f"P{di}-{pi}", "page": pi, "text": t} for pi, t in enumerate(d["pages"], 1)]})
    srt = os.path.join(work, "lecture.srt")
    if mode != "slides" and os.path.exists(srt):
        reg["segments"] = segments_from_srt(srt)
        reg["gaps"] = silence_gaps(reg["segments"])
        if not duration and reg["segments"]: reg["duration"] = reg["segments"][-1]["end"]
    frames_dir = os.path.join(work, "frames")
    ocr = read_json(os.path.join(frames_dir, "ocr.json"), []) or []
    deck_by_path = {os.path.realpath(d["file"]): d["idx"] for d in reg["decks"]}
    deck_by_name = {os.path.splitext(os.path.basename(d["file"]))[0]: d["idx"] for d in reg["decks"]}
    for i, f in enumerate(sorted((f for f in ocr if not f.get("error")), key=lambda f: f["t"]), 1):
        m = f.get("match") or {}
        pid = None
        if m.get("page"):
            di = deck_by_path.get(os.path.realpath(m.get("path") or "")) or deck_by_name.get(m.get("deck") or "")
            if di: pid = f"P{di}-{m['page']}"
        reg["frames"].append({"id": f"F{i}", "file": f["file"], "t": f["t"], "text": f.get("text", ""), "chars": f.get("chars", 0),
                              "slide": pid, "toolbar_page": (f.get("toolbar") or {}).get("page") or (None if m else f.get("page")),
                              "also_at": f.get("also_at", [])})
    cam = read_json(os.path.join(frames_dir, "cam", "cam.json"), []) or []
    for i, c in enumerate(sorted(cam, key=lambda c: c["t"]), 1):
        reg["cam"].append({"id": f"H{i}", "file": "cam/" + c["file"], "t": c["t"], "kind": c.get("kind")})
    atomic_write_json(os.path.join(job_dir, "sources.json"), reg)
    return reg

def load(job_dir):
    return read_json(os.path.join(job_dir, "sources.json"))

def index(reg):
    """id -> 来源条目(带 kind)"""
    out = {}
    if not reg: return out
    for s in reg.get("segments", []): out[s["id"]] = dict(s, kind="S")
    for d in reg.get("decks", []):
        for p in d["pages"]: out[p["id"]] = dict(p, kind="P", deck=d["name"], deck_idx=d["idx"])
    for f in reg.get("frames", []): out[f["id"]] = dict(f, kind="F")
    for c in reg.get("cam", []): out[c["id"]] = dict(c, kind="H")
    return out

def label(src):
    """引用在预览/导出里显示的文字"""
    k = src["kind"]
    if k == "S": return f"{hms(src['start'])}"
    if k == "P": return f"{src['deck']} PDF第{src['page']}页"   # PDF 页序;印刷页码无法可靠确认,不显示
    if k == "F": return f"截图 {hms(src['t'])}"
    if k == "H": return f"手写 {hms(src['t'])}"
    return src.get("id", "?")

def time_of(src):
    k = src["kind"]
    if k == "S": return src["start"]
    if k in ("F", "H"): return src["t"]
    return None
