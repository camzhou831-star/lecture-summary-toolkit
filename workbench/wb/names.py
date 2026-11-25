"""核对专名:总结写完、时间戳核对完以后,再让模型过一遍人名 / 公司 / 产品名。

语音识别常把专名听成同音或近音的字(黄仁勋 → 黄云勋、Claude → Cloud、Gartner → Garner)。
模型只返回「改哪段、改成什么」的清单,由代码照着替换:
  - 只采纳 confidence=high 的条目,其余列成「待核实」,不动原文;
  - old 必须在总结里原样出现、不超过 80 字,old 和 new 里的 [MM:SS] 时间戳必须一模一样,所以改不动时间戳和别的内容;
  - 改完重新核对格式和时间戳,原来通过、改完不通过就整份退回改之前。
这一步出任何错都只记日志,不影响任务完成。
"""
import json
import re

TS = re.compile(r"\[\d{1,3}:[0-5]\d(?:[–-]\d{1,3}:[0-5]\d)?\]")
MAX_OLD = 80

SYSTEM = {
    "zh": """你是专名校对员。下面这份总结是根据自动转写(语音识别)写的。语音识别常把人名、公司 / 机构名、产品 / 模型名、地名、作品名听错:同音或近音的字,或者英文名被听成别的英文词。你要找出这些听错的专名,给出正确写法。

规则:
1. 只处理专名。不改观点、数字、日期、时间戳和其他措辞。
2. 判断要同时看读音和上下文:读音相近,而且上下文吻合(同一处提到的公司、职位、领域、产品)。两条都满足、并且是公众熟知的人物 / 机构 / 产品时,confidence 写 "high";只满足一条,或者有好几个可能,写 "low"。
3. 你只是还原讲者说的是谁、是什么,不判断讲者说的事是真是假,也不补充事实。
4. 总结里已经有"(转写疑似:…)"这类括注的,把括注一起放进 old,在 new 里换成你的结论。
5. old 必须是总结里原样出现的一小段文字(专名本身加上紧跟的括注即可,不超过 80 字),不能包含 [MM:SS] 时间戳。同一个听错的专名在总结里出现好几处、写法不一样(有的带括注、有的不带),每种写法各列一条。
6. new 写成:正确写法(转写为"原来的写法")。例如 old 是 "黄云勋",new 是 "黄仁勋(转写为"黄云勋")"。
7. 拿不准的不要猜着改,放进 unsure。

只输出一个 JSON 代码块,不要别的文字:
```json
{"fixes": [{"old": "总结里的原文片段", "new": "替换后的文字", "heard": "转写里听错的写法(不带括注)", "name": "正确写法", "confidence": "high", "why": "一句话依据"}],
 "unsure": [{"text": "总结里的写法", "guess": "可能是什么,想不出就留空", "why": "为什么拿不准"}]}
```
没有要改的就输出 {"fixes": [], "unsure": []}。""",
    "en": """You are a proper-noun checker. The summary below was written from an automatic (speech-recognition) transcript. Speech recognition often mishears names of people, companies / organisations, products / models, places and works: similar-sounding words, or an English name heard as a different word. Find these misheard names and give the correct form.

Rules:
1. Only proper nouns. Do not change opinions, numbers, dates, timestamps or any other wording.
2. Judge by sound and by context together: it sounds similar AND the context fits (the company, role, field or product mentioned in the same place). If both hold and it is a well-known person / organisation / product, set confidence "high"; if only one holds, or several candidates fit, set "low".
3. You only restore who or what the speaker meant. Do not judge whether what they said is true, and do not add facts.
4. If the summary already has a note like "(possible transcription error: …)", include the note in "old" and replace it with your conclusion in "new".
5. "old" must be a short piece of text that appears verbatim in the summary (the name plus any note right after it, at most 80 characters) and must not contain an [MM:SS] timestamp. If the same misheard name appears in several places written differently (with or without a note), list each form separately.
6. Write "new" as: Correct Name (transcribed as "original"). E.g. old "Cloud", new "Claude (transcribed as \\"Cloud\\")".
7. If unsure, do not guess: put it under "unsure".

Output only one JSON code block, nothing else:
```json
{"fixes": [{"old": "verbatim text from the summary", "new": "replacement", "heard": "the misheard form (without any note)", "name": "correct form", "confidence": "high", "why": "one-line reason"}],
 "unsure": [{"text": "as written in the summary", "guess": "what it might be, or empty", "why": "why you are unsure"}]}
```
If there is nothing to fix, output {"fixes": [], "unsure": []}.""",
}


class NamesError(Exception):
    pass


def messages(md, lang):
    return [{"role": "system", "content": SYSTEM[lang]},
            {"role": "user", "content": "<summary>\n" + md + "\n</summary>"}]


def parse(text):
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    raw = m.group(1) if m else text.strip()
    try:
        j = json.loads(raw)
    except ValueError as e:
        raise NamesError(f"专名核对的回答不是 JSON: {e}") from e
    if not isinstance(j, dict):
        raise NamesError("专名核对的回答格式不对")
    fixes = [f for f in j.get("fixes") or [] if isinstance(f, dict)]
    unsure = [u for u in j.get("unsure") or [] if isinstance(u, dict)]
    return fixes, unsure


def apply(md, fixes):
    """按清单替换。返回 (新 md, 采纳的, 没采纳的[(条目, 原因)])"""
    used, skipped = [], []
    for f in fixes:
        old, new = str(f.get("old") or ""), str(f.get("new") or "")
        why = None
        if str(f.get("confidence", "")).lower() != "high":
            why = "把握不够"
        elif not old or not new or old == new:
            why = "清单不完整"
        elif len(old) > MAX_OLD:
            why = "要改的片段太长"
        elif TS.findall(old) != TS.findall(new):
            why = "会动到时间戳"
        elif "\n" in old or "\n" in new:
            why = "跨行"
        elif old not in md:
            why = "总结里找不到这段原文"
        if why:
            skipped.append((f, why))
            continue
        md = md.replace(old, new)
        md, more = _rest(md, str(f.get("heard") or ""), str(f.get("name") or ""), new)
        used.append(dict(f, more=more))
    return md, used, skipped


def _rest(md, heard, name, new):
    """同一个听错的词在别处还有不带括注的写法(比如时间线里只写了 Cloud),一并换成正确写法。
    只换整词(英文按单词边界),太短的(< 3 个字符)不换,刚写进去的「(转写为"…")」括注不动"""
    if len(heard) < 3 or not name or heard == name or heard in name:
        return md, 0
    left = r"(?<![A-Za-z0-9])" if heard[0].isascii() and heard[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if heard[-1].isascii() and heard[-1].isalnum() else ""
    pat = re.compile(left + re.escape(heard) + right)
    parts = re.split("(" + re.escape(new) + ")", md)          # 已替换好的那几处跳过
    n = 0
    for i in range(0, len(parts), 2):
        parts[i], k = pat.subn(name, parts[i])
        n += k
    return "".join(parts), n


def pending(skipped, unsure, used=()):
    """待核实清单:没采纳的 + 模型自己拿不准的,同一个词只列一次。
    去掉两种不用核实的:已经被采纳的那条一并改好的(含同一个听错的词、猜的也是同一个写法),
    以及猜的和原文一样的(「Downey → 可能是 Downey」)"""
    heards = [str(f.get("heard") or "") for f in used if len(str(f.get("heard") or "")) >= 3]
    done = {str(f.get("name") or "").strip() for f in used}
    rest, seen = [], set()
    for u in [{"text": f.get("old", ""), "guess": f.get("name", ""), "why": w} for f, w in skipped] + unsure:
        text = str(u.get("text", ""))
        key = re.sub(r"[((].*", "", text).strip(" \"“”")
        guess = str(u.get("guess") or "").strip()
        if not key or key in seen or guess == key:
            continue
        if (not guess or guess in done) and any(h in text for h in heards):
            continue
        seen.add(key)
        rest.append(u)
    return rest


def report(used, skipped, unsure, lang="zh"):
    """给界面和日志的清单"""
    zh = lang == "zh"
    lines = []
    if used:
        lines.append(("已校正 %d 处专名:" if zh else "Corrected %d name(s):") % len(used))
        lines += [f"  · {f['old']} → {f.get('name') or f['new']}" + ((f"(另有 {f['more']} 处一并改了)" if zh else f" (+{f['more']} more)") if f.get("more") else "") + (f"({f['why']})" if f.get("why") and zh else f" ({f['why']})" if f.get("why") else "") for f in used]
    rest = pending(skipped, unsure, used)
    if rest:
        lines.append(("待核实 %d 处(没改,请自己核对):" if zh else "To check %d item(s) (left as is):") % len(rest))
        for u in rest:
            g = u.get("guess") or ""
            lines.append(f"  · {u.get('text', '')}" + (f" → {'可能是' if zh else 'maybe'} {g}" if g else "") + (f"({u['why']})" if u.get("why") and zh else f" ({u['why']})" if u.get("why") else ""))
    if not lines:
        lines.append("✅ 没发现听错的专名" if zh else "✅ No misheard names found")
    return "\n".join(lines)
