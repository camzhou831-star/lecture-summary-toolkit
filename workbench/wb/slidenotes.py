"""只有课件(没有录播)的复习笔记:写作提示和格式核对。

课件逐页文字由 materials.slides_text 读出(PDF / .pptx);写作规则在 templates/slides.md。
核对只看程序能确定的:小节齐不齐、页码在不在课件范围内、有没有混进时间戳、复习卡够不够。
内容对不对交给后面的「审核内容」(review.py),和课程总结同一套。
"""
import os
import re

from . import config

HEADINGS = {
    "zh": ["一句话概括", "核心要点", "逐页笔记", "概念与术语", "课件里的考试 / 作业信息", "复习卡"],
    "en": ["One-line summary", "Key points", "Slide-by-slide notes", "Concepts and terms", "Exam / assignment info in the slides", "Review Cards"],
}
NOTES = {
    "zh": ["一两句话说清这份课件讲什么", "编号列表,5–12 条,每条一两句,标页码",
           "按课件顺序分几段(### pN–M 小标题),写清每段讲了什么;公式、代码、定义照抄原文再解释",
           "- **术语**:一句话解释 [课件 pN]", "只写课件上明写的考试、作业、截止日期、分值;没有就写「课件里没有」", "复习卡"],
    "en": ["One or two sentences on what the slides cover", "A numbered list of 5–12 points, one or two sentences each, with page numbers",
           "Follow the slide order in a few parts (### pN–M subheadings) and say what each part covers; copy formulas, code and definitions verbatim, then explain",
           "- **Term**: a one-sentence explanation [Slide pN]", "Only exams, assignments, deadlines and marks written on the slides; otherwise write \"None in the slides\"", "Review cards"],
}
PAGE = re.compile(r"\[(?:课件|Slide)s? p(\d+)(?:\s*[–-]\s*p?(\d+))?(?:/\d+)?\]")
TS = re.compile(r"\[\d{1,3}:[0-5]\d\]")


SEE_PAGES = ("**课件里以图为主的页已截成图片**({pages})。{how}看图后,在「逐页笔记」对应位置加一段引用块 "
             "`> 图示解读(课件 pN):……`:图里画了什么、坐标轴和图例、能看出的趋势或结论、图上标注的数值。"
             "只写图上看得到的;看不清就写看不清,不要推测;图里没有的结论不要写。有了图示解读,这一页就不用再写「以图为主,看原课件」。"
             "封面、目录、只有一个链接的页,文字已经说清楚了,不用写图示解读。")
HOW_OPEN = "用读文件 / 看图的工具打开 `{dir}/` 下的图片(PDF 页是 pNN.png,.pptx 的图是 pNN-1.jpeg 这样)。"
HOW_ATTACHED = "图片附在用户消息后面,每张前面标了是第几页。"


def data_uri(path):
    import base64
    mime = {".png": "image/png", ".gif": "image/gif"}.get(os.path.splitext(path)[1].lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def system_prompt(lang):
    tpl = open(os.path.join(config.TEMPLATES, "slides.md"), encoding="utf-8").read()
    title = "# <课件标题> — <主题>" if lang == "zh" else "# <Slide deck title> — <topic>"
    quote = ("> 引用块写:课件文件名、页数,以及「本笔记只依据课件,没有录播:没有时间戳,老师上课口头补充的内容不在其中」"
             if lang == "zh" else
             "> In a quote block: the file name, the page count, and \"These notes are based on the slides only, with no recording: no timestamps, and nothing the lecturer said in class\"")
    rows = [title, quote] + [f"{n}. `## {h}` — {d}" for n, (h, d) in enumerate(zip(HEADINGS[lang], NOTES[lang]), 1)]
    tpl = tpl.replace("{structure}", "\n".join(rows)).replace("{page_hint}", "中文笔记写 [课件 pN]" if lang == "zh" else "write [Slide pN] in English notes")
    if lang == "en":
        tpl += "\n\nWrite the notes in English (Global English: plain, short sentences). Section headings exactly as listed above."
    return tpl


def check(md, pages, lang):
    """→ (通过, 报告)。报告格式和 check_summary.py 一样(「行 N: …」),出错时交回模型改"""
    problems = []
    lines = md.split("\n")
    heads = [l[3:].strip() for l in lines if l.startswith("## ")]
    for h in HEADINGS[lang]:
        if h not in heads:
            problems.append((0, f"缺少小节「## {h}」"))
    for n, l in enumerate(lines, 1):
        if TS.search(l):
            problems.append((n, f"出现了时间戳 {TS.search(l).group(0)}:只有课件没有录播,不能写时间戳"))
        for m in PAGE.finditer(l):
            for g in m.groups():
                if g and pages and not 1 <= int(g) <= pages:
                    problems.append((n, f"页码 p{g} 超出课件范围(共 {pages} 页)"))
    cards = sum(1 for l in lines if "::" in l or re.search(r"==[^=]+==", l))
    need = 8 if pages >= 20 else 3
    if cards < need:
        problems.append((0, f"复习卡只有 {cards} 张,至少要 {need} 张"))
    if not PAGE.search(md):
        problems.append((0, "没有标任何课件页码"))
    if not problems:
        return True, f"✅ 课件笔记核对通过(共 {pages} 页,{cards} 张复习卡)"
    return False, f"❌ 课件笔记有 {len(problems)} 个问题\n" + "\n".join(
        f"  行 {n}: {p}" if n else f"  {p}" for n, p in problems)
