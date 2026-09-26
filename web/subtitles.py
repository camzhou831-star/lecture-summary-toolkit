"""字幕导入:SRT / VTT 解析、问题检查、统一写成 SRT(下游 compact / build_bundle 只认 SRT)。
导入的字幕不默认视为准确:检查结果随任务保存,并在 AI 材料里注明"字幕来自导入文件"。"""
import re

TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
CUE_RE = re.compile(TIME + r"\s*-->\s*" + TIME)

def _sec(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000

def parse(text):
    """返回 (cues, fmt);cues = [{"start","end","text","line"}],保持文件中的原始顺序"""
    text = text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    fmt = "vtt" if text.lstrip().upper().startswith("WEBVTT") else "srt"
    cues = []
    blocks = re.split(r"\n\s*\n", text.strip())
    line_no = 1
    pos = 0
    for b in blocks:
        idx = text.find(b, pos); pos = idx + len(b) if idx >= 0 else pos
        start_line = text.count("\n", 0, idx) + 1 if idx >= 0 else line_no
        lines = b.split("\n")
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None: continue                      # WEBVTT 头、NOTE、STYLE 块
        m = CUE_RE.search(lines[ti])
        if not m:
            cues.append({"start": None, "end": None, "text": " ".join(lines[ti+1:]).strip(), "line": start_line + ti, "bad_time": lines[ti].strip()})
            continue
        s = _sec(*m.groups()[0:4]); e = _sec(*m.groups()[4:8])
        body = " ".join(l.strip() for l in lines[ti+1:])
        body = re.sub(r"<[^>]+>", "", body)          # VTT 的 <v 说话人>、<c> 样式标签
        body = re.sub(r"\{\\[^}]*\}", "", body)      # SRT 里的 ASS 样式
        body = re.sub(r"\s+", " ", body).strip()
        cues.append({"start": round(s, 3), "end": round(e, 3), "text": body, "line": start_line + ti})
    return cues, fmt

def check(cues, duration=None):
    """返回 (clean_cues, issues)。issues: [{"level": "error"|"warn", "msg"}]。clean_cues 已排序、去掉无效条目。"""
    issues = []
    bad = [c for c in cues if c.get("start") is None]
    if bad:
        issues.append({"level": "warn", "msg": f"{len(bad)} 条字幕的时间格式无法识别,已跳过(第一处在第 {bad[0]['line']} 行:{bad[0]['bad_time'][:40]})"})
    good = [c for c in cues if c.get("start") is not None]
    empty = [c for c in good if not c["text"]]
    good = [c for c in good if c["text"]]
    if empty: issues.append({"level": "warn", "msg": f"{len(empty)} 条字幕没有文字,已跳过"})
    inv = [c for c in good if c["end"] < c["start"]]
    if inv:
        issues.append({"level": "warn", "msg": f"{len(inv)} 条字幕结束时间早于开始时间(第一处在第 {inv[0]['line']} 行),已按开始时间 + 2 秒修正"})
        for c in inv: c["end"] = c["start"] + 2
    disorder = sum(1 for a, b in zip(good, good[1:]) if b["start"] < a["start"] - 0.5)
    if disorder:
        issues.append({"level": "warn", "msg": f"字幕有 {disorder} 处时间顺序颠倒,已按开始时间重新排序;请留意是否导入了拼接错的文件"})
    good.sort(key=lambda c: c["start"])
    if duration:
        over = [c for c in good if c["start"] > duration + 2]
        if over:
            issues.append({"level": "error", "msg": f"{len(over)} 条字幕的时间超出视频时长 {int(duration)//60} 分钟(最晚 {int(over[-1]['start'])//60} 分)——字幕可能和视频不是同一节课"})
            good = [c for c in good if c["start"] <= duration + 2]
    if not good:
        issues.append({"level": "error", "msg": "字幕里没有任何可用的文字条目。请确认选的是字幕文件(.srt / .vtt),不是空文件或其它格式"})
    elif len(good) < 10:
        issues.append({"level": "warn", "msg": f"字幕只有 {len(good)} 条,内容可能不完整"})
    if good:
        words = sum(len(c["text"].split()) for c in good)
        span = good[-1]["end"] - good[0]["start"]
        if span > 1200 and words / max(span, 1) < 0.3:
            issues.append({"level": "warn", "msg": "字幕文字非常稀疏(每分钟不到 18 个词),可能只含部分片段"})
    return good, issues

def fmt_ts(sec):
    ms = int(round(sec * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def to_srt(cues):
    out = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}\n{fmt_ts(c['start'])} --> {fmt_ts(c['end'])}\n{c['text']}\n")
    return "\n".join(out)

def load_file(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"): return raw.decode("utf-16")
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: continue
    return raw.decode("utf-8", "replace")
