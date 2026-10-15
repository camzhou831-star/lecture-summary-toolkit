#!/usr/bin/env python3
"""打 Release 包(只用 git 已提交的文件,未跟踪的课程数据不可能混进去),中英各一套:
  dist/lecture-summary-toolkit-<版本>-zh.zip / -en.zip       完整版:只带对应语言的 README、文档、网页提示词,
                                                             并预设总结默认语言(根目录 course.json 的 output_lang)
  dist/lecture-summary-web-prompts-<版本>-zh.zip / -en.zip   网页版:只有对应语言的提示词和使用说明,不用安装
tests/、.github/ 不进包(见 .gitattributes);docs/release-notes.md 只给 Release 页面用,也不进包。
用法: build_release.py <版本,如 v0.1.0> [--out dist] [--ref HEAD]
"""
import argparse, io, json, os, re, subprocess, sys, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# 与 tests/check_no_course_content.sh 同一口径:examples/ 之外不能有媒体、字幕、课件、讲义稿、总结
COURSE_RE = re.compile(r"\.(srt|vtt|mp4|mkv|mov|webm|m4a|mp3|wav|aiff|jpg|jpeg|png|pdf|pptx|docx)$|grounded\.md$|bundle\.json$|compact\.txt$|ocr\.json$|^(课程视频|画面|总结|课件)/.+(?<!\.gitkeep)$")
REPO_URL = "https://github.com/camzhou831-star/lecture-summary-toolkit"
LANGS = ("zh", "en")
# 每种语言的包里不带的文件(另一种语言的说明与提示词)
DROP = {"zh": ("README.md", "docs/en/", "prompts/web-prompt.en.md", "docs/release-notes.md"),
        "en": ("README.zh.md", "docs/zh/", "prompts/web-prompt.zh.md", "docs/release-notes.md")}
# 包里的 README 指向被拿掉的文件时,改成指向 GitHub
RELINK = {"zh": [("[English](README.md)", f"[English]({REPO_URL}#readme)")],
          "en": [("[中文](README.zh.md)", f"[中文]({REPO_URL}/blob/main/README.zh.md)"),
                 ("[docs/zh/开发者说明.md](docs/zh/开发者说明.md)", f"[docs/zh/开发者说明.md]({REPO_URL}/blob/main/docs/zh/开发者说明.md)")]}
WEB_README = {
    "zh": """课程总结 · 网页提示词(中文)

1. 从学校课程网站(LMS)下载这节课的字幕(.srt 或 .vtt);有课件 PDF 的话也下载本讲那一份。
2. 打开任意网页 AI(ChatGPT / Claude / Gemini / Grok),新开一个对话,上传字幕和课件。
3. 打开 web-prompt.zh.md,全选复制,粘贴发送。AI 会写出带时间戳的中文总结和复习卡,最后列出考试信息请你确认。

网页版没有自动检查,时间和页码请抽查几处。想要自动检查、回跳录播和跨周考点库,请下载完整版 lecture-summary-toolkit-…-zh.zip。
""",
    "en": """Lecture Summary · Web Prompt (English)

1. Download this lecture's subtitles (.srt or .vtt) from your university's LMS, and this lecture's slide PDF if there is one.
2. Open any web AI (ChatGPT / Claude / Gemini / Grok), start a new chat, and upload the subtitles and slides.
3. Open web-prompt.en.md, copy everything, paste and send. The AI writes an English summary with timestamps and review cards, then lists exam information for you to confirm.

The web version has no automatic checks; spot-check a few times and page numbers. For automatic checks, links back to the recording and a cross-week exam bank, download the full version lecture-summary-toolkit-…-en.zip.
"""}


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, check=True).stdout


def dropped(rel, lang):
    return any(rel == d or (d.endswith("/") and rel.startswith(d)) for d in DROP[lang])


def full_package(data, commit, version, lang, out):
    path = os.path.join(out, f"lecture-summary-toolkit-{version}-{lang}.zip")
    bad = []
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        kept = [i.filename for i in src.infolist() if not i.is_dir() and not dropped(i.filename.split("/", 1)[1], lang)]
        for info in src.infolist():
            rel = info.filename.split("/", 1)[1]
            if rel and dropped(rel, lang): continue
            if info.is_dir() and not any(k.startswith(info.filename) for k in kept): continue   # 拿掉文件后变空的目录不留
            if rel and not rel.startswith("examples/") and COURSE_RE.search(rel): bad.append(rel)
            body = src.read(info)
            if rel in ("README.md", "README.zh.md"):
                text = body.decode("utf-8")
                for a, b in RELINK[lang]: text = text.replace(a, b)
                body = text.encode("utf-8")
            dst.writestr(info, body)
        dst.writestr("lecture-summary-toolkit/VERSION", f"{version} ({commit}) {lang}\n")
        dst.writestr("lecture-summary-toolkit/course.json", json.dumps({"output_lang": lang}, indent=2) + "\n")   # 总结默认语言,用户可改
    if bad:
        os.remove(path); sys.exit("❌ 发现疑似课程内容,已中止打包: " + ", ".join(bad[:10]))
    return path


def web_package(ref, commit, version, lang, out):
    path = os.path.join(out, f"lecture-summary-web-prompts-{version}-{lang}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"lecture-summary-web-prompts/web-prompt.{lang}.md", git("show", f"{ref}:prompts/web-prompt.{lang}.md"))
        z.writestr("lecture-summary-web-prompts/" + ("使用说明.txt" if lang == "zh" else "README.txt"), WEB_README[lang])
        z.writestr("lecture-summary-web-prompts/VERSION", f"{version} ({commit}) {lang}\n")
    return path


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("version"); ap.add_argument("--out", default=os.path.join(ROOT, "dist")); ap.add_argument("--ref", default="HEAD")
    a = ap.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", a.version): sys.exit(f"错误: 版本号应形如 v0.1.0,收到 {a.version}")
    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("⚠️ 工作区有未提交的改动;Release 只包含已提交的内容", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    data = git("archive", "--format=zip", "--prefix=lecture-summary-toolkit/", a.ref)
    commit = git("rev-parse", "--short", a.ref).decode().strip()
    for lang in LANGS:
        for p in (full_package(data, commit, a.version, lang, a.out), web_package(a.ref, commit, a.version, lang, a.out)):
            print(f"== {os.path.relpath(p, ROOT)}  {os.path.getsize(p) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
