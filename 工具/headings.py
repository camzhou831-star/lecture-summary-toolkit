#!/usr/bin/env python3
"""总结的中英两套小节标题,以及"哪份总结是什么语言"的约定。check_summary / add_links / exam_bank / review_pack 共用。
约定:
  - 中文总结 <视频名>.md(沿用旧文件名,旧总结不用改);英文总结 <视频名>.en.md
  - 语言只看文件名,不猜内容;标题和文件名语言不一致时 check_summary 会报错
  - 标题按前缀匹配(如 "## ⚠️ 课程通知(12:07–13:30)" 也算课程通知节)
"""
import os

LANGS = ("zh", "en")
SECTIONS = {
    "notice":   {"zh": "## ⚠️ 课程通知",     "en": "## ⚠️ Course Notices"},
    "oneliner": {"zh": "## 一句话概括",      "en": "## One-Sentence Summary"},
    "key":      {"zh": "## 核心要点",        "en": "## Key Points"},
    "timeline": {"zh": "## 章节时间线",      "en": "## Timeline"},
    "signal":   {"zh": "## 金句 / 考点信号",  "en": "## Quotes / Exam Signals"},
    "card":     {"zh": "## 复习卡",          "en": "## Review Cards"},
}
REQUIRED = ("oneliner", "key", "timeline", "signal", "card")   # 课程通知节缺了只提醒(旧总结没有)


def lang_of(path):
    return "en" if os.path.basename(path).endswith(".en.md") else "zh"


def video_name(path):
    """总结文件名 → 视频名(去掉 .md 和语言后缀 .en)"""
    b = os.path.basename(path)
    for suf in (".en.md", ".md"):
        if b.endswith(suf): return b[: -len(suf)]
    return os.path.splitext(b)[0]


def summary_name(video, lang):
    return video + (".en.md" if lang == "en" else ".md")


def heading(key, lang):
    return SECTIONS[key][lang]


def section_of(line, lang=None):
    """二级标题 → 小节 key;lang=None 时两种语言都认。不是已知小节返回 None"""
    if not line.startswith("## "): return None
    for key, hs in SECTIONS.items():
        for lg in ((lang,) if lang else LANGS):
            if line.startswith(hs[lg]): return key
    return None


def headings_lang(lines):
    """统计各语言命中的小节标题数,用来发现"文件名说英文、内容是中文"这类不一致"""
    return {lg: sum(1 for l in lines if section_of(l, lg)) for lg in LANGS}
