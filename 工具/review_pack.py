#!/usr/bin/env python3
"""给一份录播总结准备审核包:把讲义稿、srt、总结、policy.md、review.md 和需要看的截图复制到新建的临时目录,审核方只拿到这个目录。
用法: review_pack.py <总结.md> [--grounded <讲义稿>] [--srt <字幕>] [--frames-dir <画面目录>] [--out <目录>]
  默认在 <COURSE_ROOT>/课程视频/ 里按总结文件名找 <名>.grounded.md 和 <名>.srt,截图在 <COURSE_ROOT>/画面/<名>/
  截图只带两类:总结里引用的,讲义稿里标了 ⚠️(文字少 / 必须看图)的;放在审核包的 画面/ 下
输出: 审核包路径与档 1/2 的启动命令(见 skills/video-summary/review.md)
"""
import argparse, os, re, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import headings as H
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录
FRAME_RE = re.compile(r"(?:cam/)?t\d{5}s(?:-\d+)?\.jpg")

def frames_to_copy(summary_text, grounded_text):
    want = set(FRAME_RE.findall(summary_text))
    for l in grounded_text.splitlines():
        if "⚠️" in l: want.update(FRAME_RE.findall(l))
    return sorted(want)

SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "skills", "video-summary")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("summary"); ap.add_argument("--grounded"); ap.add_argument("--srt"); ap.add_argument("--frames-dir"); ap.add_argument("--out")
    a = ap.parse_args()
    if not os.path.isfile(a.summary): sys.exit(f"错误: 找不到总结 {a.summary}")
    name = H.video_name(a.summary)
    grounded = a.grounded or os.path.join(ROOT, "课程视频", name + ".grounded.md")
    if not os.path.isfile(grounded): sys.exit(f"错误: 找不到讲义稿 {grounded}(用 --grounded 指定)")
    srt = a.srt or os.path.join(ROOT, "课程视频", name + ".srt")
    out = a.out or tempfile.mkdtemp(prefix="lsk-review-")
    os.makedirs(out, exist_ok=True)
    if os.listdir(out): sys.exit(f"错误: {out} 不是空目录")
    shutil.copyfile(a.summary, os.path.join(out, "summary.md"))
    shutil.copyfile(grounded, os.path.join(out, "grounded.md"))
    if os.path.isfile(srt): shutil.copyfile(srt, os.path.join(out, "transcript.srt"))
    for f in ("policy.md", "review.md"): shutil.copyfile(os.path.join(SKILL_DIR, f), os.path.join(out, f))
    frames_dir = a.frames_dir or os.path.join(ROOT, "画面", name)
    copied, missing = 0, []
    for f in frames_to_copy(open(a.summary, encoding="utf-8").read(), open(grounded, encoding="utf-8").read()):
        src = os.path.join(frames_dir, f)
        if not os.path.isfile(src): missing.append(f); continue
        dst = os.path.join(out, "画面", f); os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst); copied += 1
    print(f"== 审核包: {out}")
    print(f"   {', '.join(sorted(os.listdir(out)))};截图 {copied} 张")
    if missing: print(f"   ⚠️ 找不到 {len(missing)} 张截图(审核方无法核对这些画面): {', '.join(missing[:5])}{' …' if len(missing) > 5 else ''}")
    print(f"   Codex:  codex exec --sandbox read-only -C \"{out}\" -o \"{out}/report.md\" \"按 review.md 审核 summary.md\" < /dev/null")
    print(f"   Claude: 开子代理,只给路径 {out},要求按其中 review.md 只读审核 summary.md")

if __name__ == "__main__":
    main()
