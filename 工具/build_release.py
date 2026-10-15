#!/usr/bin/env python3
"""打 Release 包(只用 git 已提交的文件,未跟踪的课程数据不可能混进去):
  dist/lecture-summary-toolkit-<版本>.zip     完整版:解压后用 AI 客户端打开这个文件夹即可(tests/、.github/ 不带,见 .gitattributes)
  dist/lecture-summary-web-prompts-<版本>.zip  只有网页提示词(降级模式):不用安装任何东西
用法: build_release.py <版本,如 v0.1.0> [--out dist] [--ref HEAD]
"""
import argparse, io, os, re, subprocess, sys, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# 与 tests/check_no_course_content.sh 同一口径:examples/ 之外不能有媒体、字幕、课件、讲义稿、总结
COURSE_RE = re.compile(r"\.(srt|vtt|mp4|mkv|mov|webm|m4a|mp3|wav|aiff|jpg|jpeg|png|pdf|pptx|docx)$|grounded\.md$|bundle\.json$|compact\.txt$|ocr\.json$|^(课程视频|画面|总结|课件)/.+(?<!\.gitkeep)$")
PROMPT_README = """课程总结 · 网页提示词 / Lecture Summary · Web Prompts

中文:
1. 从学校课程网站(LMS)下载这节课的字幕(.srt 或 .vtt);有课件 PDF 的话也下载本讲那一份。
2. 打开任意网页 AI(ChatGPT / Claude / Gemini / Grok),新开一个对话,上传字幕和课件。
3. 打开 web-prompt.zh.md,全选复制,粘贴发送。AI 会写出带时间戳的中文总结和复习卡,最后列出考试信息请你确认。
网页版没有自动检查,时间和页码请抽查几处。想要自动检查、回跳录播和跨周考点库,用完整版。

English:
1. Download this lecture's subtitles (.srt or .vtt) from your university's LMS, and this lecture's slide PDF if there is one.
2. Open any web AI (ChatGPT / Claude / Gemini / Grok), start a new chat, upload the subtitles and slides.
3. Open web-prompt.en.md, copy everything, paste and send. The AI writes an English summary with timestamps and review cards, then lists exam information for you to confirm.
The web version has no automatic checks; spot-check a few times and page numbers. For automatic checks, links back to the recording and a cross-week exam bank, use the full version.
"""

def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, check=True).stdout

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("version"); ap.add_argument("--out", default=os.path.join(ROOT, "dist")); ap.add_argument("--ref", default="HEAD")
    a = ap.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", a.version): sys.exit(f"错误: 版本号应形如 v0.1.0,收到 {a.version}")
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("⚠️ 工作区有未提交的改动;Release 只包含已提交的内容", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    full = os.path.join(a.out, f"lecture-summary-toolkit-{a.version}.zip")
    data = git("archive", "--format=zip", "--prefix=lecture-summary-toolkit/", a.ref)
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED) as dst:
        bad = []
        for info in src.infolist():
            rel = info.filename.split("/", 1)[1]
            if rel and not rel.startswith("examples/") and COURSE_RE.search(rel): bad.append(rel)
            dst.writestr(info, src.read(info))
        commit = git("rev-parse", "--short", a.ref).decode().strip()
        dst.writestr("lecture-summary-toolkit/VERSION", f"{a.version} ({commit})\n")
    if bad:
        os.remove(full); sys.exit("❌ 发现疑似课程内容,已中止打包: " + ", ".join(bad[:10]))
    web = os.path.join(a.out, f"lecture-summary-web-prompts-{a.version}.zip")
    with zipfile.ZipFile(web, "w", zipfile.ZIP_DEFLATED) as z:
        for lang in ("zh", "en"):
            z.writestr(f"lecture-summary-web-prompts/web-prompt.{lang}.md", git("show", f"{a.ref}:prompts/web-prompt.{lang}.md"))
        z.writestr("lecture-summary-web-prompts/README.txt", PROMPT_README)
        z.writestr("lecture-summary-web-prompts/VERSION", f"{a.version} ({commit})\n")
    for p in (full, web): print(f"== {os.path.relpath(p, ROOT)}  {os.path.getsize(p) / 1024:.0f} KB")

if __name__ == "__main__":
    main()
