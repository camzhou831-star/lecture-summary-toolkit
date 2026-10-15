#!/usr/bin/env python3
"""把 whisper 输出的 .srt 压缩成按分钟合并的 .compact.txt,并过滤常见幻觉行(纯 Python,Windows 也能跑)
用法: compact.py <字幕.srt> [输出文件,默认同名 .compact.txt]
输出格式: 每行 "[HH:MM] 该分钟内的全部文本"(方括号里是 时:分,例如 [01:41] = 1 小时 41 分),空白分钟省略
"""
import os, re, sys

# 静音段常见幻觉(整行匹配,不区分大小写、忽略首尾标点和 html 标签)
BLACKLIST = {
    "thank you", "thanks", "thank you for watching", "thanks for watching",
    "i don't know", "pewds", "bye", "you", "so", "okay", "hmm",
    "subscribe", "please subscribe", "like and subscribe",
}
# 课间倒计时幻觉,如 "We'll start again at, uh, six minutes." —— 只匹配短句,不误伤正常长句
COUNTDOWN = re.compile(r"^we'?ll start again (at|in)[, ]*(uh[, ]*)?(\d+|[a-z]+)[ -]*(minutes?|mins?)$")
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->")

def norm(t):
    t = re.sub(r"<[^>]+>", "", t)                       # 去 <i>…</i> 等标签
    t = re.sub(r"^[\s*.,!?\-]+|[\s*.,!?\-]+$", "", t)  # 去首尾标点
    return re.sub(r"\s+", " ", t).strip().lower()

def is_junk(n):
    return (not n) or (n in BLACKLIST) or bool(COUNTDOWN.match(n))

def compact_minutes(srt_text):
    """返回 {分钟: [文本, ...]},已滤幻觉和连续复读"""
    minutes, prev = {}, None
    for b in re.split(r"\n\s*\n", srt_text.replace("\r\n", "\n").strip()):
        lines = [l.strip() for l in b.strip().splitlines()]
        ti = next((i for i, l in enumerate(lines) if TIME_RE.search(l)), None)
        if ti is None: continue                             # 没有时间行的块跳过
        m = TIME_RE.search(lines[ti])
        start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
        text = re.sub(r"<[^>]+>", "", " ".join(lines[ti+1:])).strip()
        n = norm(text)
        if is_junk(n): continue
        if n == prev: continue                              # 连续重复段(whisper 复读)只留一次
        prev = n
        minutes.setdefault(start // 60, []).append(text)
    return minutes

def compact_file(src, dst=None):
    dst = dst or re.sub(r"\.srt$", "", src) + ".compact.txt"
    minutes = compact_minutes(open(src, encoding="utf-8", errors="ignore").read())
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for mi in sorted(minutes):
            f.write(f"[{mi//60:02d}:{mi%60:02d}] {' '.join(minutes[mi])}\n")
    os.replace(tmp, dst)
    return dst, len(minutes)

def main():
    if len(sys.argv) < 2: sys.exit("用法: compact.py <字幕.srt> [输出文件]")
    src = sys.argv[1]
    if not os.path.isfile(src): sys.exit(f"错误: 找不到文件 {src}")
    dst, n = compact_file(src, sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"== 完成: {n} 行 -> {dst}", file=sys.stderr)

if __name__ == "__main__":
    main()
