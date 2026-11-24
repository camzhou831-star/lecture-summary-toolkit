"""对标拆稿的统计部分(口径来自拉片流程的 srt_stats.py,2026-11-11 对标研究统一口径)。

数字一律由代码算,AI 只负责分段、标作用和新信息点、写要点:
  字数口径:汉字每个算 1;连续的英文字母或数字算 1 个词;标点和空格不算。
  总时长口径:第一句开始到最后一句结束(不含片头片尾空白)。
  信息点口径:一个能被观众复述的新事实、数字、步骤、判断或例子算 1 个;同一信息换说法重复不算(AI 逐段标注)。
分段 JSON:[{"from": 1, "to": 4, "role": "钩子", "points": 1, "note": "一句话说明"}, ...],句子序号来自逐句表,闭区间。
"""
import json
import re

TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
TOKEN = re.compile(r"[㐀-鿿豈-﫿]|[A-Za-z]+|\d+(?:[.,]\d+)*")
ROLES = {
    "zh": ["钩子", "承诺", "背景", "转折", "举例", "论证", "清单", "结尾", "广告", "其他"],
    "en": ["Hook", "Promise", "Context", "Turn", "Example", "Argument", "Takeaway list", "Ending", "Sponsor", "Other"],
}


class BreakdownError(Exception):
    pass


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (1000 if len(ms) == 3 else 10 ** len(ms))


def parse(path):
    raw = open(path, encoding="utf-8-sig", errors="replace").read().replace("\r", "")
    out = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = TS.search(l)
            if m:
                g = m.groups()
                text = re.sub(r"<[^>]+>|\{[^}]+\}", "", " ".join(lines[i + 1:]).strip())
                if text:
                    out.append((_sec(*g[:4]), _sec(*g[4:]), text))
                break
    return out


SENT_END = re.compile(r"(?<=[。！？!?；;])")
COMMA = re.compile(r"(?<=[，,、])")


def sentences(path, max_sec=6.0):
    """逐句拆稿用的"句子":whisper 常把十几秒连着说的话合成一段,这里按句号、问号、叹号切开,
    切完还超过 max_sec 秒的再按逗号切;每一小句的时间按字数在原段里按比例分。精度约 ±1 秒"""
    out = []
    for a, b, text in parse(path):
        pieces = [x.strip() for x in SENT_END.split(text) if x.strip()]
        total = sum(max(count(x), 1) for x in pieces) or 1
        t = a
        for x in pieces:
            d = (b - a) * max(count(x), 1) / total
            if d > max_sec:
                sub = [y.strip() for y in COMMA.split(x) if y.strip()]
                st = sum(max(count(y), 1) for y in sub) or 1
                for y in sub:
                    dd = d * max(count(y), 1) / st
                    out.append((t, t + dd, y)); t += dd
            else:
                out.append((t, t + d, x)); t += d
    return out


def count(text):
    return len(TOKEN.findall(text))


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def mmss(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def sentence_table(subs):
    """给 AI 看的逐句表:序号、[MM:SS] 开始时间、字数、原文"""
    rows = [f"{i} | [{mmss(a)}] | {count(t)} | {t}" for i, (a, b, t) in enumerate(subs, 1)]
    return "序号 | 开始 | 字数 | 原文\n" + "\n".join(rows)


def _join(parts):
    return "".join(x if re.search(r"[，。！？、,.!?]$", x) else x + "，" for x in parts).rstrip("，")


def edges(subs, lang="zh"):
    s0, e1 = subs[0][0], subs[-1][1]
    head = _join([t for a, b, t in subs if a < s0 + 15])
    tail = _join([t for a, b, t in subs if b > e1 - 15])
    if lang == "en":
        return (f"## 1. First 15 seconds (verbatim)\n\n[{mmss(s0)}]–[{mmss(s0 + 15)}]\n\n> {head}\n\n"
                f"## 2. Last 15 seconds (verbatim)\n\n[{mmss(e1 - 15)}]–[{mmss(e1)}]\n\n> {tail}\n")
    return (f"## 1. 开头前 15 秒(原文)\n\n[{mmss(s0)}]–[{mmss(s0 + 15)}]\n\n> {head}\n\n"
            f"## 2. 结尾最后 15 秒(原文)\n\n[{mmss(e1 - 15)}]–[{mmss(e1)}]\n\n> {tail}\n")


def extract_segments(md):
    """从 AI 回答里取出 ```segments ...``` 这一块 JSON,返回 (分段列表, 去掉这一块之后的正文)"""
    m = re.search(r"```(?:segments|json)\s*\n(\[.*?\])\s*\n```", md, re.S)
    if not m:
        raise BreakdownError("回答里没有 ```segments 分段 JSON")
    try:
        segs = json.loads(m.group(1))
    except ValueError as e:
        raise BreakdownError(f"分段 JSON 解析失败: {e}") from e
    return segs, (md[:m.start()] + md[m.end():]).strip()


def validate(segs, n):
    """分段要从第 1 句连到第 n 句,不重叠不漏句;返回问题列表"""
    probs = []
    if not isinstance(segs, list) or not segs:
        return ["分段是空的"]
    expect = 1
    for k, s in enumerate(segs, 1):
        try:
            a, b = int(s["from"]), int(s["to"])
        except (KeyError, TypeError, ValueError):
            probs.append(f"第 {k} 段缺 from / to"); continue
        if a != expect:
            probs.append(f"第 {k} 段从第 {a} 句开始,应该从第 {expect} 句开始(不能重叠或漏句)")
        if b < a or b > n:
            probs.append(f"第 {k} 段 to={b} 不对(总共 {n} 句)")
        expect = b + 1
    if expect != n + 1:
        probs.append(f"分段到第 {expect - 1} 句就结束了,总共 {n} 句")
    return probs


def stats(subs, segs, lang="zh"):
    """分段表 + 全片指标(两节 Markdown)"""
    tot_c = sum(count(t) for _, _, t in subs)
    dur = max(subs[-1][1] - subs[0][0], 0.1)
    tot_p = sum(int(s.get("points", 0) or 0) for s in segs)
    en = lang == "en"
    rows, role_dur = [], {}
    first_point, hook_end = None, None
    for k, s in enumerate(segs, 1):
        part = subs[s["from"] - 1: s["to"]]
        a = part[0][0]
        b = subs[s["to"]][0] if s["to"] < len(subs) else part[-1][1]
        d = max(b - a, 0.1)
        c = sum(count(t) for _, _, t in part)
        p = int(s.get("points", 0) or 0)
        role = str(s.get("role", ""))
        role_dur[role] = role_dur.get(role, 0) + d
        if p and first_point is None:
            first_point = a
        if hook_end is None and role in ("钩子", "Hook"):
            hook_end = b
        note = str(s.get("note", "")).replace("|", "/")
        rows.append(f"| {k} | {role} | [{mmss(a)}]–[{mmss(b)}] | {d:.1f} | {d / dur * 100:.0f}% | {c} | {c / d * 60:.0f} | {p} | {note} |")
    def share(*names):
        return f"{sum(role_dur.get(r, 0) for r in names) / dur * 100:.0f}%"
    ad = [r for r in role_dur if r in ("广告", "Sponsor")]
    if en:
        head = ("## 3. Segments\n\n| # | Role | Time | Seconds | Share | Words | Words/min | New points | Note |\n|---|---|---|---|---|---|---|---|---|\n")
        metrics = ("## 4. Whole-video metrics\n\n| Spoken length | Words | Words/min | New points | Points/min | Hook length | First point at | Example share | Takeaway share | Sponsor |\n"
                   "|---|---|---|---|---|---|---|---|---|---|\n"
                   f"| {dur:.1f}s | {tot_c} | {tot_c / dur * 60:.0f} | {tot_p} | {tot_p / dur * 60:.1f} | "
                   f"{f'{hook_end - subs[0][0]:.1f}s' if hook_end else 'none'} | {f'[{mmss(first_point)}]' if first_point is not None else 'none'} | "
                   f"{share('Example')} | {share('Takeaway list')} | {'yes' if ad else 'none'} |\n")
    else:
        head = ("## 3. 分段表\n\n| 段 | 作用 | 时间 | 秒数 | 占比 | 字数 | 字/分 | 新信息点 | 说明 |\n|---|---|---|---|---|---|---|---|---|\n")
        metrics = ("## 4. 全片指标\n\n| 口播时长 | 总字数 | 字/分 | 新信息点 | 信息点/分 | 钩子时长 | 第一个信息点出现在 | 举例段占比 | 清单段占比 | 商单段 |\n"
                   "|---|---|---|---|---|---|---|---|---|---|\n"
                   f"| {dur:.1f} 秒 | {tot_c} | {tot_c / dur * 60:.0f} | {tot_p} | {tot_p / dur * 60:.1f} | "
                   f"{f'{hook_end - subs[0][0]:.1f} 秒' if hook_end else '无'} | {f'[{mmss(first_point)}]' if first_point is not None else '无'} | "
                   f"{share('举例')} | {share('清单')} | {'有' if ad else '无'} |\n")
    return head + "\n".join(rows) + "\n\n" + metrics


def assemble(title_block, subs, segs, body, lang="zh"):
    """标题和信息块 + 代码算的 1–4 节 + AI 写的 5–7 节"""
    return f"{title_block.strip()}\n\n{edges(subs, lang)}\n{stats(subs, segs, lang)}\n{body.strip()}\n"
