"""导入 AI 回复后的检查。只检查结构与来源,**不代表内容正确**。
每条结果: {"level": "error"|"warn"|"info", "line": 行号或 0, "msg": 发生了什么, "fix": 怎么办}"""
import re
from . import templates as T
from .sources import ID_RE, ONE_ID

TS_RE = re.compile(r"(?<![\d:/.])(\d{1,3}):([0-5]\d)(?::([0-5]\d))?(?![\d:])")
MARK_SUMMARY = re.compile(r"<!--\s*LSK:summary\s+job=(\S+)")
MARK_PART = re.compile(r"<!--\s*LSK:part\s+(\d+)\s*/\s*(\d+)(?:\s+job=(\S+))?")
MARK_END = re.compile(r"<!--\s*LSK:END\s*-->")

def _issue(level, line, msg, fix=""):
    return {"level": level, "line": line, "msg": msg, "fix": fix}

def strip_wrapping(text):
    """网页版 AI 常把整篇包在 ```markdown ... ``` 里,去掉最外层围栏"""
    t = text.replace("\r\n", "\n").strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", t, re.S)
    return m.group(1).strip() if m else t

def citations(text):
    """返回 [(行号, id)]"""
    out = []
    for ln, l in enumerate(text.splitlines(), 1):
        for m in ID_RE.finditer(l):
            for i in ONE_ID.findall(m.group(1)): out.append((ln, i))
    return out

def check_truncation(text, issues, what="回复"):
    lines = [l for l in text.splitlines() if l.strip()]
    if not MARK_END.search(text):
        last = lines[-1].strip() if lines else ""
        issues.append(_issue("error", len(text.splitlines()), f"{what}末尾没有结束标记 <!-- LSK:END -->,很可能被截断了(最后一行:「{last[:40]}」)",
                             "在 AI 网页里说「继续」,把后续内容接在后面再导入;或让 AI 重新输出完整结果"))
    if text.count("```") % 2 == 1:
        issues.append(_issue("warn", 0, "代码块的 ``` 数量是单数,可能有代码块没有结束", "检查最后一个代码块是否完整"))

def check_summary(text, reg, template, mode, job_id=None, parts_info=None):
    """reg: 来源登记表(可为 None,表示没有任何来源)"""
    from .sources import index
    idx = index(reg)
    issues = []
    text = strip_wrapping(text)
    lines = text.splitlines()
    if not text.strip():
        return [_issue("error", 0, "内容是空的", "把 AI 的完整回复粘贴进来")]
    m = MARK_SUMMARY.search(text)
    if not m:
        if MARK_PART.search(text):
            issues.append(_issue("error", 0, "这是分段的「局部笔记」,不是最终笔记", "把它粘贴到对应的分段格子里;全部分段完成后再用整合提示词生成最终笔记"))
        else:
            issues.append(_issue("warn", 1, "回复开头没有识别标记 <!-- LSK:summary … -->", "如果确认是这节课的笔记可以忽略;标记只用来防止粘贴错课程"))
    elif job_id and m.group(1).strip() != job_id:
        issues.append(_issue("error", 1, f"识别标记里的任务号 {m.group(1)} 和当前任务 {job_id} 不一致——可能粘贴了另一节课的回复", "确认粘贴的是本节课的回复"))
    check_truncation(text, issues)

    # 小节
    heads = [l.strip() for l in lines if l.startswith("## ")]
    for t in T.section_titles(template, mode):
        if not any(h.startswith(t) for h in heads):
            issues.append(_issue("error", 0, f"缺少小节「{t[3:]}」", "让 AI 按提示词里的结构补上这一节"))

    # 引用
    cites = citations(text)
    bad = [(ln, i) for ln, i in cites if i not in idx]
    for ln, i in bad[:20]:
        issues.append(_issue("error", ln, f"引用的来源 [{i}] 不存在", "这是 AI 编造或抄错的编号;在资料里找到正确编号改掉,或删除这个引用"))
    if len(bad) > 20: issues.append(_issue("error", 0, f"还有 {len(bad) - 20} 处不存在的引用", ""))
    kinds_allowed = {"P"} if mode == "slides" else {"S", "P", "F", "H"}
    for ln, i in cites:
        if i[0] not in kinds_allowed:
            issues.append(_issue("error", ln, f"仅课件模式出现了转写/截图引用 [{i}]", "仅课件模式没有老师口述和录播,删除这个引用"))
    if not cites:
        issues.append(_issue("error", 0, "全文没有任何来源编号", "让 AI 按提示词第 2 条给重要结论加上 [S..] / [P..] 这样的编号"))

    # 自写时间戳:不判错(可能是题目里的时刻),但提醒;超出时长的判错
    dur = (reg or {}).get("duration")
    in_code = False
    for ln, l in enumerate(lines, 1):
        if l.strip().startswith("```"): in_code = not in_code; continue
        if in_code or l.startswith("<!--"): continue
        noted = False
        for mt in TS_RE.finditer(l):
            if re.search(r"\d{4}-\d{2}", l[max(0, mt.start() - 5):mt.end() + 3]): continue
            if mode == "slides":
                issues.append(_issue("warn", ln, f"仅课件模式出现了像时间戳的「{mt.group(0)}」", "如果是录播时间请删除——这份笔记没有录播来源")); break
            a, b, c = mt.groups()
            sec = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
            if dur and sec > dur + 5:
                issues.append(_issue("error", ln, f"时间「{mt.group(0)}」超出录播时长 {int(dur)//60} 分钟", "时间应来自来源编号,删掉这个时间或改成来源编号"))
            elif not noted:
                noted = True
                issues.append(_issue("info", ln, f"AI 自己写了时间「{mt.group(0)}」,程序无法确认它", "建议改成来源编号 [S..];如果是题目内容可以忽略"))

    # 考点符号
    section = ""
    uncited_key = 0
    for ln, l in enumerate(lines, 1):
        if l.startswith("## "): section = l
        s = l.strip()
        ids = [i for m in ID_RE.finditer(s) for i in ONE_ID.findall(m.group(1))]
        if "🎯" in s:
            if mode == "slides":
                issues.append(_issue("error", ln, "仅课件模式出现了 🎯(老师明确说会考)", "没有老师口述就不能判断老师说过什么,改成 💡"))
            elif not any(i.startswith("S") for i in ids):
                issues.append(_issue("error", ln, "🎯 标记没有引用老师原话的转写编号 [S..]", "补上老师说这句话的转写编号;找不到就改成 💡"))
        if "⭐" in s and mode == "slides":
            issues.append(_issue("error", ln, "仅课件模式出现了 ⭐(课堂重点)", "改成 💡"))
        if mode == "slides" and re.search(r"老师(强调|说|提到|要求)|课上(提到|讲)", s):
            issues.append(_issue("warn", ln, "仅课件模式出现了「老师…」「课上…」的说法", "这份笔记没有老师口述来源,请删掉或改写"))
        if any(section.startswith(h) for h in ("## 核心要点", "## 核心概念")) and re.match(r"^(\d+[.)、]|[-*])\s+\S", s) and not ids:
            uncited_key += 1
    if uncited_key:
        issues.append(_issue("warn", 0, f"核心要点/概念里有 {uncited_key} 条没有来源编号,已标为待核对", "可以让 AI 补来源,或自己对照资料核对"))

    if not any(i["level"] == "error" for i in issues):
        issues.append(_issue("info", 0, "结构与来源检查通过。这只说明格式、编号和时间有效,不代表内容一定正确", "点正文里的来源编号可以对照原文"))
    return issues

def check_part(text, k, n, reg, mode, job_id=None):
    issues = []
    text = strip_wrapping(text)
    if not text.strip(): return [_issue("error", 0, "内容是空的", "粘贴这一块对应的 AI 回复")]
    m = MARK_PART.search(text)
    if not m:
        if MARK_SUMMARY.search(text):
            issues.append(_issue("error", 0, "这是最终笔记,不是局部笔记", "请粘贴到下方「最终笔记」处"))
        else:
            issues.append(_issue("warn", 1, "回复开头没有分块标记 <!-- LSK:part k/n -->,无法确认是第几块", "确认粘贴的是第 %d 块的回复" % k))
    else:
        mk, mn = int(m.group(1)), int(m.group(2))
        if (mk, mn) != (k, n):
            issues.append(_issue("error", 1, f"这是第 {mk}/{mn} 块的回复,但粘贴在第 {k}/{n} 块", f"把它粘贴到第 {mk} 块的格子里"))
        if job_id and m.group(3) and m.group(3) != job_id:
            issues.append(_issue("error", 1, "分块标记里的任务号和当前任务不一致——可能粘贴了另一节课的回复", ""))
    if len(MARK_PART.findall(text)) > 1:
        issues.append(_issue("error", 0, "一个格子里有多个分块标记,可能把几块回复粘在了一起", "每个格子只粘贴一块的回复"))
    check_truncation(text, issues, "这一块回复")
    from .sources import index
    idx = index(reg)
    bad = [(ln, i) for ln, i in citations(text) if i not in idx]
    for ln, i in bad[:10]: issues.append(_issue("error", ln, f"引用的来源 [{i}] 不存在", "改成资料里存在的编号或删除"))
    return issues

def parts_status(parts, n):
    """parts: {k: text};返回整体问题(缺块、重复)"""
    issues = []
    missing = [k for k in range(1, n + 1) if not (parts.get(str(k)) or "").strip()]
    if missing: issues.append(_issue("error", 0, f"还缺第 {', '.join(map(str, missing))} 块的回复", "把对应块的材料发给 AI,把回复粘贴进来"))
    seen = {}
    for k, t in parts.items():
        key = re.sub(r"\s+", "", strip_wrapping(t or ""))[:2000]
        if key and key in seen:
            issues.append(_issue("error", 0, f"第 {k} 块和第 {seen[key]} 块的内容相同,可能重复粘贴了", "检查两个格子,把正确的回复粘到对应位置"))
        elif key: seen[key] = k
    return issues
