#!/usr/bin/env python3
"""校验一份录播总结:时间戳是否越界/落在无语音段、截图引用是否存在、必需小节是否齐全、标题日期是否与视频文件名一致。
用法: check_summary.py <总结.md> [--srt <字幕.srt>] [--frames-dir <画面目录>]
退出码: 0 全部通过;1 有问题(逐条打印,含行号)
"""
import argparse, os, re, sys, subprocess
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录
MONTHS = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
REQUIRED = ["## 一句话概括", "## 核心要点", "## 章节时间线", "## 金句 / 考点信号", "## 复习卡"]
WARN_HEADINGS = ["## ⚠️ 课程通知"]   # 缺了只提醒不判失败(旧总结没有)
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.]\d+\s*-->\s*(\d+):(\d+):(\d+)")

def srt_spans(path):
    spans = []
    for m in TIME_RE.finditer(open(path, encoding="utf-8", errors="ignore").read()):
        spans.append((int(m[1])*3600+int(m[2])*60+int(m[3]), int(m[4])*3600+int(m[5])*60+int(m[6])))
    return spans

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("summary"); ap.add_argument("--srt"); ap.add_argument("--frames-dir")
    a = ap.parse_args()
    name = os.path.splitext(os.path.basename(a.summary))[0]
    srt = a.srt or os.path.join(ROOT, "课程视频", name + ".srt")
    frames_dir = a.frames_dir or os.path.join(ROOT, "画面", name)
    text = open(a.summary, encoding="utf-8").read()
    lines = text.splitlines()
    problems = []; warnings = []

    # 1. 小节
    for h in REQUIRED:
        if not any(l.startswith(h) for l in lines): problems.append((0, f"缺少小节 {h}"))
    for h in WARN_HEADINGS:
        if not any(l.startswith(h) for l in lines): warnings.append(f"没有 {h} 节(新总结应保留此节,没有通知就写\"无\")")

    # 2. 标题日期 vs 文件名日期
    fm = re.search(r"- (\d{1,2}) ([A-Z][a-z]{2}) ", name)   # 文件名里的 "20-s1" 不是年份
    tm = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", lines[0] if lines else "")
    if fm and tm:
        d, mo = int(fm[1]), MONTHS.get(fm[2])
        if (int(tm[2]), int(tm[3])) != (mo, d): problems.append((1, f"标题日期 {tm[0]} 与文件名日期 {fm[1]} {fm[2]} 不一致"))
        import datetime
        y = int(tm[1]); now = datetime.date.today().year
        if y < 2020 or y > now + 1: problems.append((1, f"标题年份 {y} 可疑(当前 {now} 年)"))

    # 3. 时间戳
    duration = None; spans = []
    if os.path.exists(srt):
        spans = srt_spans(srt); duration = max(e for _, e in spans) if spans else None
        if not spans: problems.append((0, f"字幕 {srt} 里没有任何时间行,无法校验时间戳"))
        for ext in (".mp4", ".mkv", ".m4a", ".mp3"):
            v = os.path.join(ROOT, "课程视频", name + ext)
            if os.path.exists(v):
                r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", v], capture_output=True, text=True)
                try: duration = float(r.stdout.strip())
                except ValueError: pass
                break
    else:
        problems.append((0, f"找不到字幕 {srt},跳过时间戳校验"))
    for ln, l in enumerate(lines, 1):   # 占位时间(如 17:xx、39:xx–40:xx)是没查 srt 的估算
        for m in re.finditer(r"(?<![\d:])\d{1,3}:[xX]{2}\b", l): problems.append((ln, f"时间占位 {m[0]},请换成 srt 里的实际时间"))
    ts_re = re.compile(r"(?<![\d:])(\d{1,3}):(\d{2})(?![\d:])")
    in_code = False
    for ln, l in enumerate(lines, 1):
        if l.strip().startswith("```"): in_code = not in_code
        if in_code or l.startswith("#") and "通知" not in l: continue
        for m in ts_re.finditer(l):
            mm, ss = int(m[1]), int(m[2])
            if re.match(r"\d{4}-\d{2}", l[max(0, m.start()-5):m.end()+3]): continue   # 日期
            if ss >= 60: problems.append((ln, f"时间戳 {m[0]} 秒数不合法")); continue
            t = mm*60 + ss
            if duration and t > duration + 5:
                problems.append((ln, f"时间戳 {m[0]} 超出视频时长 {int(duration)//60}:{int(duration)%60:02d}"))
            elif spans and not any(s - 60 <= t <= e + 60 for s, e in spans):
                problems.append((ln, f"时间戳 {m[0]} 前后 60 秒内没有任何转写(可能落在静音段或估算错误)"))

    # 4. 截图引用
    for ln, l in enumerate(lines, 1):
        for m in re.finditer(r"(cam/)?t\d{5}s(?:-\d+)?\.jpg", l):   # cam/ 前缀是实物投影(手写)帧
            if not os.path.exists(os.path.join(frames_dir, m[0])): problems.append((ln, f"引用的截图不存在: {m[0]}"))
        for m in re.finditer(r"画面/([^/`)\]]+)/?", l):
            if not os.path.isdir(os.path.join(ROOT, "画面", m[1])): problems.append((ln, f"引用的画面文件夹不存在: 画面/{m[1]}"))

    # 5. 复习卡数量(policy.md 规定 8–15 张,不足 30 分钟的录播不设下限;一行一张,问答卡含 ::,填空卡含 ==…==)
    sec = [i for i, l in enumerate(lines) if l.startswith("## 复习卡")]
    if sec:
        body = []
        for l in lines[sec[0] + 1:]:
            if l.startswith("## "): break
            body.append(l)
        n = sum(1 for l in body if "::" in l or re.search(r"==[^=]+==", l))
        short = duration is not None and duration < 1800
        if n > 15 or (n < 8 and not short): problems.append((sec[0] + 1, f"复习卡 {n} 张,应为 8–15 张"))

    for w in warnings: print(f"  ⚠️ {w}")
    if problems:
        print(f"❌ {a.summary}: {len(problems)} 个问题")
        for ln, p in sorted(problems): print(f"  行 {ln}: {p}")
        sys.exit(1)
    print(f"✅ {a.summary}: 通过(时长 {int(duration)//60 if duration else '?'} 分钟,{len(spans)} 段转写)")

if __name__ == "__main__":
    main()
