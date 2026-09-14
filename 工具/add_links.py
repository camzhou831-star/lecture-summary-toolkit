#!/usr/bin/env python3
"""把总结里"章节时间线"一节的 [MM:SS] 改成可点击回跳录播的链接(Obsidian media-extended 支持 #t= 定位;普通 Markdown 查看器点开会从头播放)。
用法: add_links.py <总结.md> [--dry-run]
只处理 "## 章节时间线" 下、以 "- " 开头的行里第一个 [MM:SS];已带链接的行跳过(幂等)。
链接形式: [06:59](<../../课程视频/<视频名>.mp4#t=419>)
"""
import argparse, os, re, sys
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("summary"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    name = os.path.splitext(os.path.basename(a.summary))[0]
    video = next((name + ext for ext in (".mp4", ".mkv", ".m4a", ".mp3") if os.path.exists(os.path.join(ROOT, "课程视频", name + ext))), None)
    if not video: sys.exit(f"跳过: 课程视频/ 下找不到 {name} 的视频文件")
    rel = os.path.relpath(os.path.realpath(os.path.join(ROOT, "课程视频", video)), os.path.dirname(os.path.realpath(a.summary)))   # realpath 消除 /tmp→/private/tmp 之类别名
    lines = open(a.summary, encoding="utf-8").read().split("\n")
    out, n, in_section = [], 0, False
    for l in lines:
        if l.startswith("## "): in_section = l.startswith("## 章节时间线")
        if in_section and l.startswith("- ") and "#t=" not in l:   # 已带链接的行整行跳过(幂等;否则第二次会给同一行的第二个时间戳加链接)
            m = re.search(r"\[(\d{1,3}):(\d{2})\](?!\()", l)
            if m:
                sec = int(m[1])*60 + int(m[2])
                l = l[:m.end()] + f"(<{rel}#t={sec}>)" + l[m.end():]; n += 1
        out.append(l)
    if a.dry_run:
        print(f"{a.summary}: 将改 {n} 行,例如:", next((l for l in out if "#t=" in l), "")[:120])
    else:
        open(a.summary, "w", encoding="utf-8").write("\n".join(out)); print(f"{a.summary}: 已加 {n} 个链接")

if __name__ == "__main__":
    main()
