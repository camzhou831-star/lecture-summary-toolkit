#!/usr/bin/env python3
"""跨周考点库:把一个单元下所有录播总结里的"🎯 考点信号 / 金句"、"⚠️ 课程通知"、"期中/考核说明"、"复习卡"
汇总成一份 总结/<单元>/考点库.md(+ 考点库.json 结构化数据),Quiz/期中前直接从这里出模拟题,不用再逐份翻总结。
用法: exam_bank.py <单元代码|总结子目录名|某份总结.md> [--out <文件>] [--no-json] [--quiet]
      例: exam_bank.py 1002         → 汇总 <COURSE_ROOT>/总结/1002/*.md,写 总结/1002/考点库.md
          exam_bank.py 总结/1003/DEMO1003\ -\ 17\ Aug\ 20-s1-full.md   → 汇总该总结所在目录
规则:
  - 只读文件名能被 course_meta 解析(或标题里有 第N周/WN + 日期)的总结;考点库.md 自身与其它笔记跳过
  - 每条目记录:周次、日期、原文、时间戳(第一个可回跳录播)、课件页码、是否 🎯 老师明说
  - 复习卡汇总时把 `::` 改成 ` → `、`==x==` 改成 **x**,避免 Spaced Repetition 插件把考点库当第二份卡组重复排期
  - 整份文件每次重新生成,不要手改;改了某周总结后重跑即可
  - 中英分开:中文总结 <名>.md → 考点库.md;英文总结 <名>.en.md → Exam-Bank.en.md(界面文字也是英文),两种语言不混汇
退出码: 0 正常;1 找不到总结或目录
"""
import argparse, datetime, json, os, re, sys
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import headings as H
try:
    import course_meta
except Exception:   # pragma: no cover
    course_meta = None

TS_RE = re.compile(r"(?<![\d:])(\d{1,3}):(\d{2})(?![\d:])")
PAGE_RE = re.compile(r"((?:lect|L)\s?\d+[a-z]?)?\s*(?:课件\s*)?\bp\.?\s?(\d+)(?:\s*[–—-]\s*(?:p)?(\d+))?", re.I)
TITLE_WEEK_RE = re.compile(r"第\s*(\d+|[一二三四五六七八九十]+)\s*周|\bW(?:eek)?\s?(\d+)\b")
CN_NUM = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,"十一":11,"十二":12,"十三":13}
TITLE_DATE_RE = re.compile(r"[（(](\d{4}-\d{2}-\d{2})[)）]")
ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.、)])\s+")
VIDEO_EXTS = (".mp4", ".mkv", ".m4a", ".mp3")


def section_kind(heading):
    """把二级标题归类;不关心的返回 None"""
    k = H.section_of(heading)
    if k in ("notice", "signal", "card"): return k
    if k: return None
    h = heading.lstrip("#").strip()
    if h.startswith("⚠️") or "课程通知" in h: return "notice"
    if "考点信号" in h or "金句" in h: return "signal"
    if "复习卡" in h: return "card"
    if any(w in h for w in ("期中", "期末", "考核", "考试", "Quiz", "quiz", "Midterm", "Mid-semester", "Final", "Exam", "Assessment")): return "exam"
    return None


def parse_summary(path, cfg=None):
    name = H.video_name(path)
    lines = open(path, encoding="utf-8").read().splitlines()
    if not lines or not lines[0].startswith("# "): return None
    title = lines[0][2:].strip()
    meta = course_meta.parse(os.path.basename(path), cfg or {}) if course_meta else None
    wm = TITLE_WEEK_RE.search(title); dm = TITLE_DATE_RE.search(title)
    week = (meta or {}).get("week") if meta else None
    if wm: week = int(wm[2]) if wm[2] else (CN_NUM.get(wm[1]) or int(wm[1]))   # 标题里明写的周次优先(与 course_meta 冲突时以人写的为准)
    date = dm[1] if dm else (meta or {}).get("date")
    if week is None and date is None: return None
    tm = re.search(r"[)）]\s*[—–-]+\s*(.+)$", title)
    topic = tm[1].strip() if tm else title
    unit = (meta or {}).get("unit") or (re.match(r"([A-Z]{4}\d{4})", name) or [None, None])[1]
    video = next((name + e for e in VIDEO_EXTS if os.path.exists(os.path.join(ROOT, "课程视频", name + e))), name + ".mp4")
    items = {"notice": [], "signal": [], "exam": [], "card": []}
    kind = None; cur = None; in_code = False
    for ln, l in enumerate(lines[1:], 2):
        if l.strip().startswith("```"): in_code = not in_code; continue
        if in_code: continue
        if l.startswith("## "): kind = section_kind(l); cur = None; continue
        if not kind or not l.strip(): continue
        if ITEM_RE.match(l):
            indent = len(l) - len(l.lstrip())
            text = ITEM_RE.sub("", l).strip()
            if kind == "card" and "::" not in text and "==" not in text: continue
            if indent > 0 and cur is not None and kind != "card":   # 子条目并进上一条
                cur["text"] += " ▸ " + text; cur["raw"] += "\n" + l; continue
            cur = {"line": ln, "text": text, "raw": l}
            items[kind].append(cur)
        elif kind == "exam" and l.startswith("###"):
            cur = {"line": ln, "text": l.lstrip("#").strip(), "raw": l}; items[kind].append(cur)
    for kind, lst in items.items():
        for it in lst:
            it["flag"] = "🎯" in it["text"]
            body = re.sub(r"\(<[^>]*#t=\d+>\)", "", it["text"])   # 去掉已有回跳链接再找时间戳
            body = re.sub(r"\d{4}-\d{2}-\d{2}", "", body)
            it["timestamps"] = [int(m[1]) * 60 + int(m[2]) for m in TS_RE.finditer(body) if int(m[2]) < 60]
            it["pages"] = sorted({(m[1] or "").lower().replace(" ", "") + " p" + m[2] + (("–" + m[3]) if m[3] else "") for m in PAGE_RE.finditer(body)})
            it["pages"] = [p.strip() for p in it["pages"]]
    return {"file": os.path.basename(path), "unit": unit, "week": week, "date": date, "topic": topic, "video": video, "items": items}


def fmt_ts(sec): return f"{sec // 60}:{sec % 60:02d}"


def strip_ts_link(text):
    return re.sub(r"\[(\d{1,3}:\d{2})\]\(<[^>]*>\)", r"\1", text)


def linked(it, s, out_dir):
    """条目文本 + 第一个时间点的回跳链接:原文里已有 [MM:SS] 就把它变成链接,否则加在最前面"""
    text = strip_ts_link(it["text"])
    if not it["timestamps"]: return text
    sec = it["timestamps"][0]
    rel = os.path.relpath(os.path.realpath(os.path.join(ROOT, "课程视频", s["video"])), os.path.realpath(out_dir))
    lk = f"[{fmt_ts(sec)}](<{rel}#t={sec}>)"
    m = re.search(r"\[(\d{1,3}):(\d{2})\]", text)
    if m and int(m[1]) * 60 + int(m[2]) == sec: return text[:m.start()] + lk + text[m.end():]
    return lk + " " + text


def card_plain(text):
    text = re.sub(r"==([^=]+)==", r"**\1**", text)
    return re.sub(r"\s*::\s*", " → ", text, 1)


OUT_NAME = {"zh": "考点库.md", "en": "Exam-Bank.en.md"}
T = {   # 考点库界面文字;条目原文不翻译
    "zh": {"title": "{unit} 考点库(自动汇总)",
           "gen": "> 由 `工具/exam_bank.py` 从 `{src}/` 下 {n} 份总结生成于 {today};**不要手改**,改了某周总结后重跑即可。",
           "cover": "> 覆盖:", "sep": "、",
           "flag": "## 🎯 老师明说会考 / 不考 / 怎么考({n} 条)", "flag_none": "- (暂无;总结里用 🎯 标出的条目会汇总到这里)",
           "exam": "## 📝 考核说明专节({n} 条,来自总结里单列的期中/考核小节)", "exam_none": "- (无)",
           "notice": "## 📢 课程通知(按周,{n} 条)", "signal": "## 💬 金句 / 考点信号(按周,{n} 条)", "none": "- 无",
           "card": "## 🃏 复习卡题库({n} 张;正式排期请在各周总结里用 Spaced Repetition 插件,这里只作出题素材)",
           "usage": ["## 出模拟题的用法", "",
                     "1. 先看 🎯 节:老师说过的题型、范围、\"不给部分分\"之类的规则原样照搬。",
                     "2. 每周 💬 节至少出 1 题;判断题把错误藏在 because/since 从句里(Quiz 1 的出题规律)。",
                     "3. 🃏 题库改写成选择/填空;答案只认课件与老师原话,不认常识推断。"]},
    "en": {"title": "{unit} Exam Bank (auto-generated)",
           "gen": "> Generated by `工具/exam_bank.py` from {n} summaries in `{src}/` on {today}. **Do not edit by hand**; re-run after changing a weekly summary.",
           "cover": "> Covers: ", "sep": ", ",
           "flag": "## 🎯 Lecturer said what will / won't be examined, or how ({n})", "flag_none": "- (None yet; items marked 🎯 in the summaries are collected here)",
           "exam": "## 📝 Assessment sections ({n}, from midterm / assessment sections in the summaries)", "exam_none": "- (None)",
           "notice": "## 📢 Course notices (by week, {n})", "signal": "## 💬 Quotes / exam signals (by week, {n})", "none": "- None",
           "card": "## 🃏 Review card pool ({n} cards; schedule reviews in each weekly summary with the Spaced Repetition plugin, this list is only material for practice questions)",
           "usage": ["## How to write practice questions", "",
                     "1. Start with the 🎯 section: copy question types, scope and rules such as \"no partial marks\" exactly as the lecturer said them.",
                     "2. Write at least one question per week from the 💬 section; for true/false questions, hide the error in a because/since clause.",
                     "3. Turn the 🃏 pool into multiple-choice or fill-in-the-blank questions; accept only answers backed by the slides or the lecturer's words."]},
}


def render(unit, summaries, out_dir, src_dir, lang="zh"):
    t = T[lang]; today = datetime.date.today().isoformat()
    wk = lambda s: f"W{s['week']}" if s["week"] is not None else "W?"
    tag = lambda s: f"**{wk(s)} {(s['date'] or '')[5:]}**"
    L = ["# " + t["title"].format(unit=unit), "",
         t["gen"].format(src=os.path.relpath(src_dir, ROOT), n=len(summaries), today=today),
         t["cover"] + t["sep"].join(f"{wk(s)}({s['date']})" for s in summaries), ""]
    flagged = [(s, it) for s in summaries for k in ("signal", "notice", "exam") for it in s["items"][k] if it["flag"]]
    L += [t["flag"].format(n=len(flagged)), ""]
    L += [f"- {tag(s)} {linked(it, s, out_dir)}" for s, it in flagged] or [t["flag_none"]]
    exams = [(s, it) for s in summaries for it in s["items"]["exam"]]
    L += ["", t["exam"].format(n=len(exams)), ""]
    L += [f"- {tag(s)} {linked(it, s, out_dir)}" for s, it in exams] or [t["exam_none"]]
    n_notice = sum(len(s["items"]["notice"]) for s in summaries)
    L += ["", t["notice"].format(n=n_notice), ""]
    for s in summaries:
        L += [f"### {wk(s)}({s['date']})— {s['topic']}", ""]
        L += [f"- {linked(it, s, out_dir)}" for it in s["items"]["notice"]] or [t["none"]]
        L.append("")
    n_sig = sum(len(s["items"]["signal"]) for s in summaries)
    L += [t["signal"].format(n=n_sig), ""]
    for s in summaries:
        L += [f"### {wk(s)}({s['date']})— {s['topic']}", ""]
        L += [f"- {linked(it, s, out_dir)}" for it in s["items"]["signal"]] or [t["none"]]
        L.append("")
    n_card = sum(len(s["items"]["card"]) for s in summaries)
    L += [t["card"].format(n=n_card), ""]
    for s in summaries:
        L += [f"### {wk(s)}({s['date']})", ""]
        L += [f"- {card_plain(it['text'])}" for it in s["items"]["card"]] or [t["none"]]
        L.append("")
    L += t["usage"] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", help="单元代码 / 总结子目录 / 某份总结.md")
    ap.add_argument("--out"); ap.add_argument("--no-json", action="store_true"); ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    t = a.target
    if os.path.isfile(t): src = os.path.dirname(os.path.abspath(t))
    elif os.path.isdir(t): src = os.path.abspath(t)
    elif os.path.isdir(os.path.join(ROOT, "总结", t)): src = os.path.join(ROOT, "总结", t)
    else:
        cfg = course_meta.load_config(ROOT) if course_meta and hasattr(course_meta, "load_config") else {}
        alias = ((cfg.get("units") or {}).get(t) or {}).get("alias")
        src = os.path.join(ROOT, "总结", alias) if alias and os.path.isdir(os.path.join(ROOT, "总结", alias)) else None
        if not src: sys.exit(f"错误: 找不到总结目录(试过 {t}、总结/{t})")
    cfg = course_meta.load_config(ROOT) if course_meta and hasattr(course_meta, "load_config") else {}
    by_lang = {lg: [] for lg in H.LANGS}
    for f in sorted(os.listdir(src)):
        if not f.endswith(".md") or f in OUT_NAME.values() or f.startswith("考点库"): continue
        try: s = parse_summary(os.path.join(src, f), cfg)
        except Exception as e:   # 单份坏文件不拖累整体
            print(f"  ⚠️ 跳过 {f}: {e}", file=sys.stderr); s = None
        if s: by_lang[H.lang_of(f)].append(s)
    if not any(by_lang.values()): sys.exit(f"错误: {src} 下没有可解析的录播总结(标题需含 第N周 / Week N / WN 与 (YYYY-MM-DD))")
    if a.out and all(by_lang.values()): sys.exit("错误: 目录里中英文总结都有,--out 只能指定一份;去掉 --out 会分别写 考点库.md 与 Exam-Bank.en.md")
    for lang, summaries in by_lang.items():
        if summaries: write_bank(a, src, lang, summaries)


def write_bank(a, src, lang, summaries):
    summaries.sort(key=lambda s: ((s["week"] if s["week"] is not None else 99), s["date"] or ""))
    unit = next((s["unit"] for s in summaries if s["unit"]), os.path.basename(src))
    out = a.out or os.path.join(src, OUT_NAME[lang])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w", encoding="utf-8").write(render(unit, summaries, os.path.dirname(os.path.abspath(out)), src, lang))
    if not a.no_json:
        j = os.path.splitext(out)[0] + ".json"
        json.dump({"unit": unit, "lang": lang, "generated": datetime.date.today().isoformat(), "summaries": summaries}, open(j, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        n = {k: sum(len(s["items"][k]) for s in summaries) for k in ("signal", "notice", "exam", "card")}
        fl = sum(1 for s in summaries for k in ("signal", "notice", "exam") for it in s["items"][k] if it["flag"])
        missing = [s["file"] for s in summaries if not any(it["flag"] for k in ("signal", "notice", "exam") for it in s["items"][k])]
        print(f"== 考点库: {unit} {len(summaries)} 周 → {out}")
        print(f"   🎯 {fl} 条 · 考点信号 {n['signal']} · 通知 {n['notice']} · 考核专节 {n['exam']} · 复习卡 {n['card']}")
        if missing: print(f"   ⚠️ 这些总结没有任何 🎯 标记(老师没明说考点,或写总结时漏标): {', '.join(missing)}")


if __name__ == "__main__":
    main()
