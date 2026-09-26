"""导出:通用 Markdown(默认)、Obsidian Markdown(可选)、独立 HTML(可打印成 PDF)。"""
import html, os, re, urllib.parse
from .sources import ID_RE, ONE_ID, label, time_of
from .checks import strip_wrapping, MARKER_ONLY_LINE
from . import mdrender

MARKER_LINE = re.compile(MARKER_ONLY_LINE.pattern, re.M | re.I)

def _clean(text):
    return MARKER_LINE.sub("", strip_wrapping(text)).strip() + "\n"

def _cited(text, idx):
    seen = []
    for m in ID_RE.finditer(text):
        for i in ONE_ID.findall(m.group(1)):
            if i in idx and i not in seen: seen.append(i)
    return seen

def _appendix(ids, idx):
    out = ["", "---", "", "## 来源", ""]
    for i in ids:
        s = idx[i]
        if s["kind"] == "S": body = s["text"][:160] + ("…" if len(s["text"]) > 160 else "")
        elif s["kind"] == "P": body = " ".join(s["text"].split())[:120]
        elif s["kind"] == "F": body = ("对应课件 " + s["slide"]) if s.get("slide") else " ".join((s.get("text") or "").split())[:100]
        else: body = "手写页截图 " + s["file"]
        out.append(f"- **{i}**〔{label(s)}〕{body}")
    return out

def to_markdown(text, idx, obsidian=False, video_path=None, frames_dir=None):
    body = _clean(text)
    def rep(m):
        parts = []
        for i in ONE_ID.findall(m.group(1)):
            s = idx.get(i)
            if not s: parts.append(f"〔{i}?〕"); continue
            t = time_of(s)
            if obsidian and video_path and t is not None:
                url = "file://" + urllib.parse.quote(os.path.abspath(video_path)) + f"#t={int(t)}"
                parts.append(f"[{label(s)}](<{url}>)")
            elif obsidian and frames_dir and s["kind"] in ("F", "H"):
                parts.append(f"![[{os.path.join(frames_dir, s['file'])}|300]]")
            else:
                parts.append(f"〔{label(s)}〕")
        return "".join(parts)
    out = ID_RE.sub(rep, body)
    if not obsidian:
        # 复习卡 "问题::答案" 是 Obsidian Spaced Repetition 语法;通用格式改成问答两行
        out = re.sub(r"^(\s*[-*]?\s*)([^\n:]+?)::(.+)$", lambda m: f"{m.group(1)}**问:**{m.group(2).strip()} **答:**{m.group(3).strip()}", out, flags=re.M)
        out = re.sub(r"==(.+?)==", r"**\1**", out)
    out = out.rstrip() + "\n" + "\n".join(_appendix(_cited(body, idx), idx)) + "\n"
    return out

CSS = """body{font:16px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:820px;margin:32px auto;padding:0 16px;color:#1d1d1f}
h1{font-size:1.6em}h2{margin-top:1.6em;border-bottom:1px solid #ddd;padding-bottom:.2em}code{background:#f3f3f3;padding:0 .3em;border-radius:3px}
pre{background:#f6f6f6;padding:12px;overflow:auto}blockquote{border-left:3px solid #ccc;margin:0;padding-left:12px;color:#555}
.cite{font-size:.8em;color:#0b5cad;border:1px solid #bcd;border-radius:4px;padding:0 4px;margin:0 1px;background:#f4f8fc;white-space:nowrap}
.card{display:block}.card .q{font-weight:600}.card .q::after{content:" → "}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}
.src{font-size:.9em;color:#444}"""

def to_html(text, idx, title):
    def cite(i, s):
        if not s: return f'<span class="cite">[{html.escape(i)}?]</span>'
        return f'<a class="cite" href="#src-{i}">{html.escape(label(s))}</a>'
    body = mdrender.render(text, idx, cite)
    ids = _cited(_clean(text), idx)
    src = ['<h2>来源</h2><ol class="src">']
    for i in ids:
        s = idx[i]
        if s["kind"] == "S": t = s["text"]
        elif s["kind"] == "P": t = s["text"]
        elif s["kind"] == "F": t = ("对应课件 " + s["slide"] + "\n" if s.get("slide") else "") + (s.get("text") or "")
        else: t = "手写页截图 " + s["file"]
        src.append(f'<li id="src-{i}"><b>{i}</b> {html.escape(label(s))}<br><span>{html.escape(t[:600]).replace(chr(10), "<br>")}</span></li>')
    src.append("</ol>")
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>
{body}
{''.join(src)}
</body></html>"""
