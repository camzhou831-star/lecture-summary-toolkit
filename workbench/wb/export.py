"""导出总结:Word(.docx,图片嵌进去)和 Markdown + 图片(.zip)。PDF 在网页里用浏览器打印(见 app.js 的 printSummary)。

总结里能出现的图只有画面拉片的 /api/tasks/{id}/shotfile/{名字}(接触表、代表帧),导出时换成本地文件。
Markdown → Word 只认总结里实际会用到的写法:# 标题、段落、- / 1. 列表(可缩进)、> 引用、| 表格 |、``` 代码块、---、
![图](地址)、**粗** *斜* `代码` [文字](链接)。
"""
import io
import os
import re
import zipfile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

IMG = re.compile(r"!\[([^\]]*)\]\((/api/tasks/(\d+)/shotfile/([^)\s]+))\)")
LINK_FILE = re.compile(r"\((/api/tasks/(\d+)/shotfile/([^)\s]+))\)")
INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|(?<![*\w])\*[^*\n]+\*(?!\*))")


def local_file(task_root, name):
    from . import shotflow
    p = os.path.join(task_root, shotflow.DIR, os.path.basename(name))
    return p if os.path.isfile(p) else None


def files_in(md, task_root):
    """总结里引用到的本地文件 {名字: 路径}"""
    out = {}
    for m in LINK_FILE.finditer(md):
        p = local_file(task_root, m.group(3))
        if p:
            out[os.path.basename(m.group(3))] = p
    return out


def md_zip(md, task_root, stem):
    """→ (bytes, 文件名, 类型):没有图就直接给 .md;有图就打包 .md + images/"""
    files = files_in(md, task_root)
    if not files:
        return md.encode("utf-8"), f"{stem}.md", "text/markdown; charset=utf-8"
    body = LINK_FILE.sub(lambda m: f"(images/{os.path.basename(m.group(3))})" if os.path.basename(m.group(3)) in files else m.group(0), md)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}/{stem}.md", body)
        for name, p in files.items():
            z.write(p, f"{stem}/images/{name}")
    return buf.getvalue(), f"{stem}.zip", "application/zip"


# ---------- 数学公式 → Word 里能直接读的文字 ----------
# 网页和 PDF 用 KaTeX 排版;Word 里换成 Unicode:x^2 → x²、a_{n+1} → aₙ₊₁、\frac{1}{2} → 1/2、\le → ≤ ……
MATH_MD = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)|\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\((.+?)\\\)"
                     r"|(?<![\\$\w])\$(?![\s$])([^\n$`　-〿一-鿿＀-￯]+?)(?<![\s\\])\$(?![\d$])")
SUP = dict(zip("0123456789+-=()nijkx", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱʲᵏˣ"))
SUB = dict(zip("0123456789+-=()aeoxijknmt", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓᵢⱼₖₙₘₜ"))
SCRIPT = re.compile(r"([\^_])(\{([^{}]*)\}|([A-Za-z0-9]))")


def _scripts(tex):
    def one(m):
        body = m.group(3) if m.group(3) is not None else m.group(4)
        table = SUP if m.group(1) == "^" else SUB
        if body and all(ch in table for ch in body):
            return "".join(table[ch] for ch in body)
        return f"{m.group(1)}({body})" if len(body) > 1 else m.group(1) + body
    prev = None
    while prev != tex:
        prev, tex = tex, SCRIPT.sub(one, tex)
    return tex


def tex_text(tex):
    from pylatexenc.latex2text import LatexNodes2Text
    try:
        out = LatexNodes2Text(math_mode="text").latex_to_text(_scripts(tex))
    except Exception:
        return tex
    return re.sub(r"\s+", " ", out).strip()


def plain_math(md):
    """把总结里的公式换成可读文字(代码里的不动)"""
    def rep(m):
        if m.group(1):
            return m.group(1)
        if m.group(2) is not None or m.group(3) is not None:
            return "\n\n" + tex_text(m.group(2) if m.group(2) is not None else m.group(3)) + "\n\n"
        return tex_text(m.group(4) if m.group(4) is not None else m.group(5))
    return MATH_MD.sub(rep, md)


# ---------- Markdown → Word ----------
def _font(doc):
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")    # 中文字体(Mac 上没有会自动换成苹方)
    for s in ("Heading 1", "Heading 2", "Heading 3", "Heading 4", "Title"):
        try:
            h = doc.styles[s]
        except KeyError:
            continue
        h.font.color.rgb = RGBColor(0x1F, 0x2A, 0x24)
        rpr = h.element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:eastAsia"), "微软雅黑")
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2.2)


def _runs(par, text, bold=False):
    """一行文字里的 **粗** *斜* `代码` [文字](链接) → run(链接只留文字;时间戳 [12:34](…) 留成 12:34)"""
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            r = par.add_run(text[pos:m.start()]); r.bold = bold or None
        tok = m.group(0)
        if tok.startswith("**"):
            r = par.add_run(tok[2:-2]); r.bold = True
        elif tok.startswith("`"):
            r = par.add_run(tok[1:-1]); r.font.name = "Menlo"; r.font.size = Pt(9.5)
        elif tok.startswith("["):
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok).groups()
            r = par.add_run(label); r.bold = bold or None
            if url.startswith("http"):
                r.font.color.rgb = RGBColor(0x2F, 0x6F, 0x5A)
        else:
            r = par.add_run(tok[1:-1]); r.italic = True; r.bold = bold or None
        pos = m.end()
    if pos < len(text):
        r = par.add_run(text[pos:]); r.bold = bold or None


def _fit(path, max_w=16.0, max_h=22.0):
    """图最宽 16 cm、最高 22 cm(一页放得下),按比例缩"""
    try:
        from PIL import Image
        w, h = Image.open(path).size
    except Exception:
        return {"width": Cm(max_w)}
    return {"width": Cm(max_w)} if h / w * max_w <= max_h else {"height": Cm(max_h)}


def _shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def _table(doc, rows, task_root):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]      # 去掉 |---| 分隔行
    if not cells:
        return
    n = max(len(r) for r in cells)
    t = doc.add_table(rows=len(cells), cols=n)
    t.style = "Table Grid"
    t.autofit = False
    # 列宽按每列文字长短分(图片列按 3 cm 算),铺满版心
    def weight(c):
        return 14 if IMG.search(c) else min(max(len(IMG.sub("", c)), 3.5), 40)
    w = [max((weight(r[j]) if j < len(r) else 2) for r in cells) for j in range(n)]
    total_cm = 16.6
    widths = [Cm(total_cm * x / sum(w)) for x in w]
    tblPr = t._tbl.tblPr
    tw = OxmlElement("w:tblW"); tw.set(qn("w:w"), str(int(total_cm * 567))); tw.set(qn("w:type"), "dxa")
    for old in tblPr.findall(qn("w:tblW")):
        tblPr.remove(old)
    tblPr.append(tw)
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
    for gc, wd in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(wd.cm * 567)))
    for i, r in enumerate(cells):
        for j in range(n):
            cell = t.cell(i, j)
            cell.width = widths[j]
            text = r[j] if j < len(r) else ""
            p = cell.paragraphs[0]
            img = IMG.search(text)
            if img and local_file(task_root, img.group(4)):
                p.add_run().add_picture(local_file(task_root, img.group(4)), width=Cm(3))
                text = IMG.sub("", text).strip()
            if text:
                _runs(p, text.replace("<br>", "\n"), bold=(i == 0))
            for run in p.runs:
                run.font.size = Pt(9)
            if i == 0:
                _shade(cell, "E8F0EB")
    doc.add_paragraph()


def to_docx(md, task_root, title=""):
    doc = Document()
    _font(doc)
    lines = plain_math(md.replace("\r\n", "\n")).split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1; continue
        if s.startswith("```"):                                   # 代码块
            buf, i = [], i + 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            p = doc.add_paragraph(); r = p.add_run("\n".join(buf)); r.font.name = "Menlo"; r.font.size = Pt(9)
            i += 1; continue
        if s.startswith("|"):                                     # 表格
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i]); i += 1
            _table(doc, rows, task_root); continue
        m = re.match(r"(#{1,6})\s+(.*)", s)
        if m:                                                     # 标题
            level = len(m.group(1))
            h = doc.add_heading(level=0 if level == 1 else min(level - 1, 4))
            _runs(h, m.group(2).strip())
            i += 1; continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):              # 分隔线
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.add_run("· · ·")
            i += 1; continue
        img = IMG.fullmatch(s)
        if img:                                                   # 单独一行的图
            p_img = local_file(task_root, img.group(4))
            if p_img:
                doc.add_picture(p_img, **_fit(p_img))
                if img.group(1):
                    cap = doc.add_paragraph(img.group(1)); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cap.runs[0].font.size = Pt(9); cap.runs[0].font.color.rgb = RGBColor(0x5D, 0x6B, 0x62)
            i += 1; continue
        if s.startswith(">"):                                     # 引用块(连续几行合成一段,行内换行保留)
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            p = doc.add_paragraph(style="Quote" if "Quote" in [st.name for st in doc.styles] else None)
            for k, b in enumerate(buf):
                if k:
                    p.add_run().add_break()
                _runs(p, b)
            continue
        lm = re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", line)
        if lm:                                                    # 列表
            depth = min(len(lm.group(1).replace("\t", "    ")) // 2, 2)
            numbered = lm.group(2)[0].isdigit()
            style = ("List Number" if numbered else "List Bullet") + ("" if depth == 0 else f" {depth + 1}")
            try:
                p = doc.add_paragraph(style=style)
            except KeyError:
                p = doc.add_paragraph(style="List Number" if numbered else "List Bullet")
            _runs(p, lm.group(3))
            i += 1; continue
        buf = [s]                                                 # 普通段落(到空行或别的块为止)
        i += 1
        while i < n and lines[i].strip() and not re.match(r"\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|!\[)", lines[i]):
            buf.append(lines[i].strip()); i += 1
        p = doc.add_paragraph()
        for k, b in enumerate(buf):
            if k:
                p.add_run().add_break()
            _runs(p, b)
    if title:
        doc.core_properties.title = title[:200]
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
