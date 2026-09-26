"""课程配置(网页工作台用,存在 工作台数据/courses.json):名称、授课语言、笔记语言、默认模板、已确认的术语。
不依赖作者自己的课程;不填课程也能开始(归到"未分类")。术语自动提取只给候选,用户确认后才会使用。"""
import os, re, threading, time
from collections import Counter
from .util import data_root, read_json, atomic_write_json, now

_lock = threading.Lock()

def _path():
    return os.path.join(data_root(), "courses.json")

def all_courses():
    return (read_json(_path(), {}) or {}).get("courses", {})

def get(cid):
    return all_courses().get(cid) if cid else None

def upsert(cid, fields):
    with _lock:
        data = read_json(_path(), {}) or {}
        cs = data.setdefault("courses", {})
        if not cid:
            base = re.sub(r"[^A-Za-z0-9]+", "", fields.get("code") or "") or "c"
            cid = f"{base.lower()}-{int(time.time()) % 100000}"
        c = cs.setdefault(cid, {"created": now(), "glossary": []})
        for k in ("name", "code", "lang", "note_lang", "template", "obsidian"):
            if k in fields and fields[k] is not None: c[k] = fields[k]
        if "glossary" in fields:
            c["glossary"] = _clean_terms(fields["glossary"])
        c["updated"] = now()
        atomic_write_json(_path(), data)
        return cid, c

def _clean_terms(terms):
    out = []
    for t in terms or []:
        t = " ".join(str(t).split())[:60]
        if t and t not in out: out.append(t)
    return out[:200]

def glossary(cid):
    c = get(cid)
    return list(c.get("glossary", [])) if c else []

def find_by_code(code):
    if not code: return None
    for cid, c in all_courses().items():
        if (c.get("code") or "").upper() == code.upper(): return cid
    return None

STOP = set("""The This That These Those What When Where Which Why How And For With From Into Your You Our Can Will Not But Have Has
Example Examples Note Notes Summary Outline Overview Introduction Question Questions Answer Lecture Week Page Slide Today Next Also
Each Other Some Any All Its Then There Here Such More Most Very Just Only First Second Third One Two Three Figure Table Section Chapter""".split())

def term_candidates(text, limit=40):
    """从课件文字里找可能的专有名词:全大写缩写(RACC、MC/DC)、驼峰/带数字的标识符、反复出现的大写开头短语"""
    cnt = Counter()
    for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,}(?:[/-][A-Z0-9]+)*\b", text):
        w = m.group(0)
        if len(w) >= 2 and not w.isdigit(): cnt[w] += 1
    for m in re.finditer(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b|\b[A-Za-z]+_[A-Za-z0-9_]+\b", text):
        cnt[m.group(0)] += 1
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", text):
        ph = m.group(1)
        if ph.split()[0] not in STOP: cnt[ph] += 1
    cands = [(w, n) for w, n in cnt.items() if n >= 2 and w not in STOP]
    cands.sort(key=lambda x: (-x[1], x[0]))
    return [w for w, _ in cands[:limit]]
