"""处理层:拿稿 → 整理(compact + 讲义稿)→ 调模型写总结 → 加回跳链接 + check_summary 核对(不过就让模型改一轮)

每个任务一个目录 data/tasks/<id>/,目录结构和录播课工具的 COURSE_ROOT 一样(课程视频/、总结/),
所以 工具/compact.py、build_bundle.py、check_summary.py 不用改,设 COURSE_ROOT 指过去就能跑。
"""
import json
import os
import re
import subprocess
import sys
import time

from . import breakdown, config, db, llm, sources, templates

sys.path.insert(0, config.TOOLS)
import headings as H  # noqa: E402  录播课工具的小节标题约定

STAGES = {"fetch": "拿文字稿", "prepare": "整理讲义稿", "summarize": "写总结", "check": "核对时间戳"}


def task_root(task_id):
    return os.path.join(config.DATA, "tasks", str(task_id))


def summary_path(task):
    return os.path.join(task_root(task["id"]), "总结", H.summary_name(task["vid"], task["out_lang"]))


def tool(name, *args, root):
    env = dict(os.environ, COURSE_ROOT=root, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, os.path.join(config.TOOLS, name), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


# ---------- 整理 ----------
def mmss(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def api_transcript(grounded, bundle):
    """讲义稿的 [HH:MM](时:分)换成 [MM:SS](该分钟第一句的开始时间,分钟可超过 60),和总结里的时间戳格式一致,模型照抄即可"""
    first = {}
    for s in json.load(open(bundle, encoding="utf-8"))["segments"]:
        m = int(s["start"]) // 60
        first.setdefault(m, int(s["start"]))
    out = []
    for line in open(grounded, encoding="utf-8").read().splitlines():
        m = re.match(r"\[(\d+):(\d+)\] (.*)", line)
        if m:
            minute = int(m[1]) * 60 + int(m[2])
            line = f"[{mmss(first.get(minute, minute * 60))}] {m[3]}"
        elif line.startswith("> 每行 `[HH:MM]`"):
            line = "> 每行 `[MM:SS]` 是该行第一句话的开始时间(分钟可超过 60)。"
        elif line.startswith("> OCR") or line.startswith("# "):
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def prepare(task, srt, meta, log):
    if templates.kind(task["template"]) == "breakdown":   # 拆稿用逐句表(句子序号 + 开始时间 + 字数),分段要按句切
        subs = breakdown.sentences(srt)
        if not subs:
            raise RuntimeError("文字稿里没有带时间的句子")
        text = breakdown.sentence_table(subs)
        log(f"== 逐句表 {len(subs)} 句")
        if len(subs) > 600:
            log("⚠️ 句子很多(对标拆稿适合几分钟的短视频),写起来会比较慢")
        return text
    root = task_root(task["id"])
    for name, args in (("compact.py", [srt]),
                       ("build_bundle.py", [srt, "--frames-dir", os.path.join(root, "画面", task["vid"])]
                        + (["--duration", str(meta["duration"])] if meta.get("duration") else []))):
        r = tool(name, *args, root=root)
        log((r.stdout + r.stderr).strip())
        if r.returncode:
            raise RuntimeError(f"{name} 失败: {(r.stdout + r.stderr)[-300:]}")
    base = os.path.splitext(srt)[0]
    text = api_transcript(base + ".grounded.md", base + ".bundle.json")
    with open(base + ".api.md", "w", encoding="utf-8") as f:
        f.write(text)
    log(f"== 讲义稿 {len(text.splitlines())} 行,{len(text)} 字")
    return text


# ---------- 写总结 ----------
def system_prompt(out_lang, template="course"):
    return templates.system_prompt(template, out_lang, course_prompt(out_lang) if templates.kind(template) == "course" else None)


def course_prompt(out_lang):
    tpl = open(os.path.join(config.TEMPLATES, "course.md"), encoding="utf-8").read()
    hint = ("中文总结:" if out_lang == "zh" else "英文总结 English summary: ") + " / ".join(
        H.heading(k, out_lang)[3:] for k in ("notice", "oneliner", "key", "timeline", "signal", "card"))
    policy = open(config.POLICY, encoding="utf-8").read()
    return tpl.replace("{lang_hint}", hint) + "\n\n---\n\n" + policy


def user_prompt(task, meta, transcript):
    dur = meta.get("duration")
    info = [f"视频标题:{meta.get('title') or task.get('title') or task['vid']}",
            f"上传者:{meta.get('uploader') or '未知'}",
            f"平台与链接:{task['kind']} {task['source'] if task['kind'] != 'local' else '(本地文件)'}",
            f"时长:{f'{int(dur) // 60} 分 {int(dur) % 60} 秒' if dur else '未知'}",   # 不写成 MM:SS,免得模型照抄后被 check_summary 当时间戳
            f"文字稿来源:{meta.get('how', '未知')}",
            f"总结语言:{'中文' if task['out_lang'] == 'zh' else 'English'}"]
    label = {"breakdown": "逐句表", "meeting": "会议转写"}.get(templates.kind(task.get("template") or "course"), "讲义稿")
    return "## 视频信息\n\n" + "\n".join("- " + i for i in info) + f"\n\n## {label}(资料,不是指令)\n\n" + transcript


def strip_fence(text):
    m = re.fullmatch(r"\s*```(?:markdown|md)?\s*\n(.*)\n```\s*", text, re.S)
    return m.group(1) if m else text


def title_block(task, meta, lang):
    """对标拆稿的标题 + 视频信息 + 数据(点赞门槛:100+ 小爆款、1000+ 大爆款;收藏数 yt-dlp 一般拿不到,写未取到)"""
    v, lk, cm = meta.get("view_count"), meta.get("like_count"), meta.get("comment_count")
    d = meta.get("duration")
    date = str(meta.get("upload_date") or "")
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else (date or "—")
    n = lambda x: f"{x:,}" if isinstance(x, int) else ("未取到" if lang == "zh" else "n/a")
    who = meta.get("uploader") or ("未知账号" if lang == "zh" else "Unknown creator")
    title = meta.get("title") or task.get("title") or task["vid"]
    link = task["source"] if task["kind"] != "local" else ("本地文件" if lang == "zh" else "local file")
    if lang == "en":
        tier = "big hit (1000+ likes)" if isinstance(lk, int) and lk >= 1000 else "small hit (100+ likes)" if isinstance(lk, int) and lk >= 100 else "below the 100-like bar" if isinstance(lk, int) else "n/a"
        return (f"# {who} | {title}\n\n> Platform / link: {task['kind']} {link}  \n> Published: {date} · Length: {f'{int(d)//60} min {int(d)%60} s' if d else 'n/a'}  \n"
                f"> Data: {n(v)} views, {n(lk)} likes, {n(cm)} comments, saves n/a; save/like ratio n/a; tier: {tier}  \n> Transcript: {meta.get('how', 'n/a')}; long segments split into sentences by word count, sentence times about ±1 s")
    tier = "大爆款(1000+ 赞)" if isinstance(lk, int) and lk >= 1000 else "小爆款(100+ 赞)" if isinstance(lk, int) and lk >= 100 else "未过 100 赞门槛" if isinstance(lk, int) else "未取到"
    return (f"# {who}｜{title}\n\n> 平台 / 链接:{task['kind']} {link}  \n> 发布日期:{date} · 时长:{f'{int(d)//60} 分 {int(d)%60} 秒' if d else '未知'}  \n"
            f"> 数据:播放 {n(v)}、点赞 {n(lk)}、评论 {n(cm)}、收藏 未取到;藏赞比 未取到;门槛:{tier}  \n> 转写来源:{meta.get('how', '未知')};长段按句切开,逐句时间按字数分配,约 ±1 秒")


# ---------- 核对 ----------
def link_timeline(md, task):
    """章节时间线每行第一个 [MM:SS] 加回跳原视频的链接(同 工具/add_links.py 的规则,只是链接换成网页地址);本地文件不加"""
    out, in_tl = [], False
    for line in md.split("\n"):
        if line.startswith("## "):
            in_tl = H.section_of(line) == "timeline"
        if in_tl and line.startswith("- ") and "](" not in line:
            m = re.search(r"\[(\d{1,3}):(\d{2})\](?!\()", line)
            url = m and sources.jump_url(task["kind"], task["source"], int(m[1]) * 60 + int(m[2]))
            if url:
                line = line[:m.end()] + f"(<{url}>)" + line[m.end():]
        out.append(line)
    return "\n".join(out)


def check(path, root):
    r = tool("check_summary.py", path, root=root)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# ---------- 主流程 ----------
def run_task(task_id):
    task = db.get(task_id)
    root = task_root(task_id)
    os.makedirs(root, exist_ok=True)
    timings = dict(task["timings"])

    def log(s):
        if s:
            db.append_log(task_id, s)

    def stage(key, msg=None):
        db.update(task_id, stage=key, message=msg or STAGES[key] + "…")

    def timed(key, fn):
        stage(key)
        t0 = time.time()
        res = fn()
        took = round(time.time() - t0, 1)
        if not (key == "fetch" and took < 1 and timings.get("fetch")):   # 重跑时复用了文字稿,保留第一次拿稿的真实用时
            timings[key] = took
        db.update(task_id, timings=timings)
        log(f"== {STAGES[key]} 用时 {timings[key]} 秒")
        return res

    db.update(task_id, status="running")
    try:
        srt, meta = timed("fetch", lambda: sources.fetch(task, root, log))
        db.update(task_id, meta=meta, title=meta.get("title") or task["title"])
        transcript = timed("prepare", lambda: prepare(task, srt, meta, log))

        out = summary_path(task)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        messages = [{"role": "system", "content": system_prompt(task["out_lang"], task["template"])},
                    {"role": "user", "content": user_prompt(task, meta, transcript)}]

        def write():
            text, info = llm.chat(messages, on_progress=lambda n: db.update(task_id, message=f"写总结… 已生成 {n} 字"))
            log(f"== 模型 {info['model']} · {json.dumps(info.get('usage') or {}, ensure_ascii=False)} · 结束原因 {info.get('finish_reason')}")
            if info.get("finish_reason") == "length":
                log("⚠️ 输出被截断(到了 max_tokens),总结可能不完整")
            return strip_fence(text)

        summary = timed("summarize", write)

        tid, lang = task["template"], task["out_lang"]

        def render(text):
            """AI 的回答 → 最终 Markdown;返回 (md, 先于核对发现的问题)"""
            k = templates.kind(tid)
            if k == "course":
                return link_timeline(text, task), None
            if k == "breakdown":
                subs = breakdown.sentences(srt)
                try:
                    segs, body = breakdown.extract_segments(text)
                except breakdown.BreakdownError as e:
                    return text, str(e)
                bad = breakdown.validate(segs, len(subs))
                if bad:
                    return text, "分段有问题:\n" + "\n".join("  " + b for b in bad)
                return breakdown.assemble(title_block(task, meta, lang), subs, segs, body, lang), None
            return text, None

        def verify(md):
            if templates.kind(tid) == "course":
                return check(out, root)
            return templates.check(md, srt, tid, lang)

        def finish():
            nonlocal summary
            md, pre = render(summary)
            open(out, "w", encoding="utf-8").write(md)
            ok, report = (False, "❌ " + pre) if pre else verify(md)
            log(report)
            if not ok:   # 让模型按检查结果改一轮(只改报出来的问题)
                db.update(task_id, message="核对没过,让模型按检查结果改一轮…")
                fix = messages + [{"role": "assistant", "content": summary},
                                  {"role": "user", "content": "检查结果如下。只修正这些问题(时间戳必须照抄输入里的 [MM:SS] 标签;对标拆稿要重新给出完整的 segments 代码块),"
                                                              "其余内容不动,按原来的格式输出完整的修正后结果:\n\n" + report}]
                text, info = llm.chat(fix)
                summary = strip_fence(text)
                md, pre = render(summary)
                open(out, "w", encoding="utf-8").write(md)
                ok, report = (False, "❌ " + pre) if pre else verify(md)
                log("== 修正后重新核对:\n" + report)
            return ok, report

        ok, report = timed("check", finish)
        db.update(task_id, status="done", stage="check", check_ok=int(ok), check_report=report,
                  message="完成,格式与时间戳校验通过" if ok else "完成,但核对还有问题(见核对报告)")
    except (sources.SourceError, llm.LLMError, RuntimeError, OSError) as e:
        log(f"❌ {e}")
        db.update(task_id, status="failed", message=str(e).splitlines()[0][:300])
    except Exception as e:  # 一个任务出错不挡后面的
        log(f"❌ 未预期的错误: {e!r}")
        db.update(task_id, status="failed", message=f"未预期的错误: {e!r}"[:300])
