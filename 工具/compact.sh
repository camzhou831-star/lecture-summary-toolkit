#!/usr/bin/env bash
# 把 whisper 输出的 .srt 压缩成按分钟合并的 .compact.txt,并过滤常见幻觉行
# 用法: compact.sh <字幕.srt> [输出文件,默认同名 .compact.txt]
# 输出格式: 每行 "[HH:MM] 该分钟内的全部文本"(方括号里是 时:分,例如 [01:41] = 1 小时 41 分),空白分钟省略
set -euo pipefail
in="${1:?用法: compact.sh <字幕.srt> [输出文件]}"
out="${2:-${in%.srt}.compact.txt}"
[ -f "$in" ] || { echo "错误: 找不到文件 $in" >&2; exit 1; }
python3 - "$in" "$out" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
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
text_all = open(src, encoding="utf-8", errors="ignore").read().replace("\r\n", "\n")
minutes = {}   # minute -> list of texts
prev = None
for b in re.split(r"\n\s*\n", text_all.strip()):
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
with open(dst, "w", encoding="utf-8") as f:
    for mi in sorted(minutes):
        f.write(f"[{mi//60:02d}:{mi%60:02d}] {' '.join(minutes[mi])}\n")
print(f"== 完成: {len(minutes)} 行 -> {dst}", file=sys.stderr)
PY
