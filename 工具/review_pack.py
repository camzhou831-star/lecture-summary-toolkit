#!/usr/bin/env python3
"""给一份录播总结准备审核包:把讲义稿、srt、总结、policy.md、review.md 复制到新建的临时目录,审核方只拿到这个目录。
用法: review_pack.py <总结.md> [--grounded <讲义稿>] [--srt <字幕>] [--out <目录>]
  默认在 <COURSE_ROOT>/课程视频/ 里按总结文件名找 <名>.grounded.md 和 <名>.srt
输出: 审核包路径与档 1/2 的启动命令(见 skills/video-summary/review.md)
"""
import argparse, os, shutil, sys, tempfile
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录
SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "skills", "video-summary")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("summary"); ap.add_argument("--grounded"); ap.add_argument("--srt"); ap.add_argument("--out")
    a = ap.parse_args()
    if not os.path.isfile(a.summary): sys.exit(f"错误: 找不到总结 {a.summary}")
    name = os.path.splitext(os.path.basename(a.summary))[0]
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
    print(f"== 审核包: {out}")
    print(f"   {', '.join(sorted(os.listdir(out)))}")
    print(f"   Codex:  codex exec --sandbox read-only -C \"{out}\" -o \"{out}/report.md\" \"按 review.md 审核 summary.md\" < /dev/null")
    print(f"   Claude: 开子代理,只给路径 {out},要求按其中 review.md 只读审核 summary.md")

if __name__ == "__main__":
    main()
