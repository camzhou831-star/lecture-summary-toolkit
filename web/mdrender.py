"""安全的 Markdown → HTML(只支持笔记里用得到的语法)。
先把全部文字做 HTML 转义,再加标签:模型回复里的 <script>、onerror= 等永远只会显示成文字,不会执行。"""
import html, re
from .sources import ID_RE, ONE_ID, label
from .checks import strip_wrapping

MARKER = re.compile(r"^\s*<!--\s*LSK:.*-->\s*$")

def _inline(s, cite):
    """s 已转义"""
    codes = []
    def keep_code(m):
        codes.append(m.group(1)); return f"\x00{len(codes)-1}\x00"
    s = re.sub(r"`([^`]+)`", keep_code, s)
    s = ID_RE.sub(lambda m: "".join(cite(i) for i in ONE_ID.findall(m.group(1))), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"==(.+?)==", r"<mark>\1</mark>", s)
    def link(m):
        text, url = m.group(1), html.unescape(m.group(2)).strip("<>")
        if re.match(r"^https?://", url):
            return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{text}</a>'
        return text
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", s)
    return s

def render(text, idx, cite_html=None):
    """idx: 来源 id -> 条目。cite_html(id, src_or_None) -> 引用按钮的 HTML"""
    def default_cite(i):
        src = idx.get(i)
        if not src:
            return f'<span class="cite bad" title="不存在的来源">[{i}?]</span>'
        return f'<button type="button" class="cite k{src["kind"]}" data-id="{i}" title="查看来源 {i}">{html.escape(label(src))}</button>'
    cite = (lambda i: cite_html(i, idx.get(i))) if cite_html else default_cite
    lines = strip_wrapping(text).splitlines()
    out, i = [], 0
    list_stack = []   # ["ul"|"ol"]
    def close_lists():
        while list_stack: out.append(f"</{list_stack.pop()}>")
    para = []
    def flush_para():
        if para: out.append("<p>" + "<br>".join(_inline(html.escape(p), cite) for p in para) + "</p>"); para.clear()
    while i < len(lines):
        raw = lines[i]
        if MARKER.match(raw): i += 1; continue
        if raw.strip().startswith("```"):
            flush_para(); close_lists()
            lang = raw.strip()[3:].strip()
            buf = []; i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"): buf.append(lines[i]); i += 1
            i += 1
            out.append(f'<pre><code data-lang="{html.escape(lang, quote=True)}">' + html.escape("\n".join(buf)) + "</code></pre>")
            continue
        s = raw.rstrip()
        if not s.strip():
            flush_para(); close_lists(); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            flush_para(); close_lists()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(html.escape(m.group(2)), cite)}</h{n}>"); i += 1; continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", s):
            flush_para(); close_lists(); out.append("<hr>"); i += 1; continue
        if s.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para(); close_lists()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"): rows.append(lines[i]); i += 1
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(html.escape(c), cite)}</th>" for c in cells(rows[0])) + "</tr></thead><tbody>")
            for r in rows[2:]: out.append("<tr>" + "".join(f"<td>{_inline(html.escape(c), cite)}</td>" for c in cells(r)) + "</tr>")
            out.append("</tbody></table>"); continue
        if s.lstrip().startswith(">"):
            flush_para(); close_lists()
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"): buf.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append("<blockquote>" + "<br>".join(_inline(html.escape(b), cite) for b in buf) + "</blockquote>"); continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)", s)
        if m:
            flush_para()
            kind = "ol" if m.group(2)[0].isdigit() else "ul"
            depth = len(m.group(1).replace("\t", "  ")) // 2
            while len(list_stack) > depth + 1: out.append(f"</{list_stack.pop()}>")
            if len(list_stack) < depth + 1: out.append(f"<{kind}>"); list_stack.append(kind)
            elif list_stack[-1] != kind: out.append(f"</{list_stack.pop()}>"); out.append(f"<{kind}>"); list_stack.append(kind)
            body = m.group(3)
            if "::" in body and not body.startswith("::"):
                q, a = body.split("::", 1)
                out.append(f'<li class="card"><span class="q">{_inline(html.escape(q), cite)}</span><span class="a">{_inline(html.escape(a), cite)}</span></li>')
            else:
                out.append(f"<li>{_inline(html.escape(body), cite)}</li>")
            i += 1; continue
        if "::" in s and not list_stack and not s.startswith("::"):
            flush_para()
            q, a = s.split("::", 1)
            out.append(f'<div class="card"><span class="q">{_inline(html.escape(q), cite)}</span><span class="a">{_inline(html.escape(a), cite)}</span></div>')
            i += 1; continue
        close_lists(); para.append(s.strip()); i += 1
    flush_para(); close_lists()
    return "\n".join(out)
