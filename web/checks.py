"""导入 AI 回复后的检查。只检查结构与来源,**不代表内容正确**。
每条结果: {"level": "error"|"warn"|"info", "line": 行号或 0, "msg": 发生了什么, "fix": 怎么办}"""
import re
from . import templates as T
from .sources import ID_RE, ONE_ID

TS_RE = re.compile(r"(?<![\d:/.])(\d{1,3}):([0-5]\d)(?::([0-5]\d))?(?![\d:])")
# 标记用看得见的文字(网页版会把 HTML 注释渲染成看不见,手动复制时会丢);旧的注释写法也认
MARK_SUMMARY = re.compile(r"LSK[:：\s]\s*(?:summary|笔记)\s+job\s*=\s*([0-9a-z-]+)", re.I)
MARK_PART = re.compile(r"LSK[:：\s]\s*(?:part|分段)\s+(\d+)\s*/\s*(\d+)(?:\s+job\s*=\s*([0-9a-z-]+))?", re.I)
MARK_END = re.compile(r"LSK[:：\s]\s*(?:END|结束)", re.I)
MARKER_ONLY_LINE = re.compile(r"^\s*(?:<!--\s*)?[【\[]?\s*LSK[:：\s].{0,80}?(?:】|\]|-->)?\s*$", re.I)

def _issue(level, line, msg, fix=""):
    return {"level": level, "line": line, "msg": msg, "fix": fix}

def strip_wrapping(text):
    """网页版 AI 常把整篇包在 ```markdown ... ``` 里,去掉最外层围栏"""
    t = text.replace("\r\n", "\n").strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", t, re.S)
    return m.group(1).strip() if m else t

def norm_heading(l):
    """「## 1. 一句话概括:」「### **核心概念**」「## 核心概念(本节)」→ 「一句话概括」「核心概念」"""
    t = re.sub(r"^\s*#+\s*", "", l.strip())
    t = re.sub(r"[*_`]", "", t)
    t = re.sub(r"^(\d+|[一二三四五六七八九十]+)\s*[.、)）:]\s*", "", t)
    t = re.sub(r"^[^\w\u4e00-\u9fff]+", "", t)          # 行首 emoji / 符号
    t = re.split(r"[\s((:：—-]", t, 1)[0]
    return t

QUOTE_RE = re.compile(r"依据\s*[::]?\s*[「“\"『](.+?)[」”\"』]")

def quote_of(line):
    m = QUOTE_RE.search(line) or re.search(r"[「“『](.{4,}?)[」”』]", line)
    return m.group(1).strip() if m else None

def _norm_words(t):
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", (t or "").lower())

def quote_in(q, src):
    """依据原文是否出现在来源里:规范化后连续出现,或 80% 以上的词出现(容忍转写标点/大小写差异)"""
    qw, sw = _norm_words(q), _norm_words(src)
    if not qw: return False
    if " ".join(qw) in " ".join(sw): return True
    ss = set(sw)
    return len(qw) >= 3 and sum(w in ss for w in qw) / len(qw) >= 0.8

def citations(text):
    """返回 [(行号, id)]"""
    out = []
    for ln, l in enumerate(text.splitlines(), 1):
        for m in ID_RE.finditer(l):
            for i in ONE_ID.findall(m.group(1)): out.append((ln, i))
    return out

def check_truncation(text, issues, what="回复", structure_ok=True):
    """没有结束标记:结构也不完整 → 很可能截断(错误);结构完整 → 只提醒,用户确认完整即可,不逼着重新生成"""
    lines = [l for l in text.splitlines() if l.strip()]
    if not MARK_END.search(text):
        last = lines[-1].strip() if lines else ""
        if structure_ok:
            issues.append(_issue("warn", len(text.splitlines()), f"{what}末尾没有结束标记【LSK 结束】(最后一行:「{last[:40]}」)",
                                 "如果你确认 AI 的回复是完整的,可以忽略;否则在 AI 那里说「继续」,把后面的内容接上再导入"))
        else:
            issues.append(_issue("error", len(text.splitlines()), f"{what}末尾没有结束标记,且缺少后面的小节,很可能被截断了(最后一行:「{last[:40]}」)",
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
            issues.append(_issue("warn", 1, "回复开头没有识别标记【LSK 笔记 job=…】,无法自动确认是不是这节课的笔记", "请确认你粘贴的是这节课的回复;确认无误可以忽略"))
    elif job_id and m.group(1).strip() != job_id:
        issues.append(_issue("error", 1, f"识别标记里的任务号 {m.group(1)} 和当前任务 {job_id} 不一致——可能粘贴了另一节课的回复", "确认粘贴的是本节课的回复"))
    # 小节:容忍常见的格式差异(标题级别、编号、加粗、冒号),只要名字对得上就算有;不改写原文
    heads = [norm_heading(l) for l in lines if re.match(r"^\s*#{2,4}\s", l)]
    missing = [t for t in T.section_titles(template, mode) if norm_heading(t) not in heads]
    for t in missing:
        issues.append(_issue("error", 0, f"缺少小节「{t[3:]}」", "让 AI 按提示词里的结构补上这一节"))
    check_truncation(text, issues, structure_ok=not missing)

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

    # 考点符号。程序只能确认可验证的事:有没有引用、引用类型对不对、给出的依据原文能不能在引用的来源里找到;
    # 找到了也只说明"原文确实这么写",不代表 AI 的解读正确。
    section = ""
    uncited_key = 0
    for ln, l in enumerate(lines, 1):
        if re.match(r"^\s*#{1,6}\s", l):
            if not l.startswith("# "): section = norm_heading(l)
            continue                                   # 标题行里的 🎯 / ⭐ 只是装饰,不当作一条考点
        s = l.strip()
        ids = [i for m in ID_RE.finditer(s) for i in ONE_ID.findall(m.group(1))]
        if "🎯" in s:
            ok_ids = [i for i in ids if i in idx and i[0] in (("P",) if mode == "slides" else ("S", "P"))]
            if not ok_ids:
                issues.append(_issue("error", ln, "🎯(明确考试信息)没有引用可核对的来源" + ("(仅课件模式只能引用课件 [P..])" if mode == "slides" else "(应引用转写 [S..] 或课件 [P..])"),
                                     "补上说这句话的来源编号;找不到明确依据就改成 💡"))
            else:
                q = quote_of(s)
                if not q:
                    issues.append(_issue("warn", ln, "🎯 没有给出依据原文", "按提示词写成「——依据:「原文片段」[S..]」,方便核对"))
                elif not any(quote_in(q, idx[i].get("text", "")) for i in ok_ids):
                    issues.append(_issue("warn", ln, f"🎯 的依据原文「{q[:40]}」在引用的来源里没有找到", "点开来源核对;可能是 AI 翻译或改写了原文,也可能引错了编号"))
        if "⭐" in s and mode == "slides":
            issues.append(_issue("warn", ln, "仅课件模式出现了 ⭐(课堂重点需要老师口述作依据)", "改成 💡;如果课件明确写了考试信息,用 🎯 并附课件原文"))
        if mode == "slides" and re.search(r"老师(强调|说|提到|要求)|课上(提到|讲)", s):
            issues.append(_issue("warn", ln, "仅课件模式出现了「老师…」「课上…」的说法", "这份笔记没有老师口述来源,请删掉或改写"))
        if any(section == norm_heading(h) for h in ("## 核心要点", "## 核心概念")) and re.match(r"^(\d+[.)、]|[-*])\s+\S", s) and not ids:
            uncited_key += 1
    if uncited_key:
        issues.append(_issue("warn", 0, f"核心要点/概念里有 {uncited_key} 条没有来源编号,已标为待核对", "可以让 AI 补来源,或自己对照资料核对"))

    if not any(i["level"] == "error" for i in issues):
        issues.append(_issue("info", 0, "结构与来源检查通过。这只说明格式、编号、引用类型和时间有效,不代表内容一定正确", "点正文里的来源编号可以对照原文"))
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
            issues.append(_issue("warn", 1, f"回复开头没有分段标记【LSK 分段 k/n】,无法自动确认是第几段;已按你选择的格子(第 {k} 段)保存", f"请确认这是第 {k} 段的回复"))
    else:
        mk, mn = int(m.group(1)), int(m.group(2))
        if (mk, mn) != (k, n):
            issues.append(_issue("error", 1, f"这是第 {mk}/{mn} 块的回复,但粘贴在第 {k}/{n} 块", f"把它粘贴到第 {mk} 块的格子里"))
        if job_id and m.group(3) and m.group(3) != job_id:
            issues.append(_issue("error", 1, "分块标记里的任务号和当前任务不一致——可能粘贴了另一节课的回复", ""))
    if len(MARK_PART.findall(text)) > 1:
        issues.append(_issue("error", 0, "一个格子里有多个分块标记,可能把几块回复粘在了一起", "每个格子只粘贴一块的回复"))
    heads = [norm_heading(l) for l in text.splitlines() if re.match(r"^\s*#{2,4}\s", l)]
    check_truncation(text, issues, "这一块回复", structure_ok=all(norm_heading(t) in heads for t, _ in T.PART_SECTIONS))
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
