"""课程资料:课件 PDF 的逐页文字,以及本地视频的画面(抽帧 → 去重 → OCR → 对课件页码)。

和录播课工具同一套脚本(工具/extract_frames.py、dedup_frames.py、ocr_frames.py、match_slides.py),
产物放在任务目录里:课件/*.pdf、画面/<视频名>/t<秒>s.jpg + ocr.json。build_bundle.py 会把画面文字和页码并进讲义稿。
缺 tesseract / pdftotext 时只记日志,照常用文字稿写总结。
"""
import glob
import os
import shutil
import subprocess
import sys

from . import config

sys.path.insert(0, config.TOOLS)
import deps  # noqa: E402

SLIDES_DIR = "课件"
MAX_SLIDES_CHARS = 80000     # 课件文字太长时截断(大约 60 页的英文课件)


def slides_dir(root):
    return os.path.join(root, SLIDES_DIR)


def slide_pdfs(root):
    return sorted(glob.glob(os.path.join(glob.escape(slides_dir(root)), "*.pdf")))


def frames_dir(root, vid):
    return os.path.join(root, "画面", vid)


def _pdf_pages(path):
    if deps.find("pdftotext"):
        r = subprocess.run([deps.exe("pdftotext"), "-layout", "-enc", "UTF-8", path, "-"], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"pdftotext 读不了 {os.path.basename(path)}")
        pages = r.stdout.decode("utf-8", "replace").split("\f")
        return pages[:-1] if pages and not pages[-1].strip() else pages
    try:
        import pypdf
    except ImportError:
        raise RuntimeError("读课件要 pdftotext(macOS: brew install poppler;Windows: winget install oschwartz10612.Poppler)")
    return [p.extract_text() or "" for p in pypdf.PdfReader(path).pages]


def slides_text(root, log):
    """课件逐页文字,给写总结和审核用。没有课件返回空字符串"""
    out = []
    for pdf in slide_pdfs(root):
        try:
            pages = _pdf_pages(pdf)
        except RuntimeError as e:
            log(f"⚠️ {e},这份课件没用上")
            continue
        n = len(pages)
        blank = sum(1 for p in pages if len(p.strip()) < 20)
        if n and blank > n / 2:
            log(f"⚠️ 课件 {os.path.basename(pdf)} 大半页没有文字层(扫描版或图片版),只能用到少量文字")
        out.append(f"### 课件 {os.path.basename(pdf)}(共 {n} 页)")
        for i, p in enumerate(pages, 1):
            lines = [l.rstrip() for l in p.splitlines() if l.strip()]
            out.append(f"\n[课件 p{i}/{n}]\n" + ("\n".join(lines) if lines else "(这一页没有文字)"))
        log(f"== 课件 {os.path.basename(pdf)}:{n} 页")
    text = "\n".join(out).strip()
    if len(text) > MAX_SLIDES_CHARS:
        log(f"⚠️ 课件文字有 {len(text)} 字,只用前 {MAX_SLIDES_CHARS} 字(只上传本讲那份课件就不会截断)")
        text = text[:MAX_SLIDES_CHARS] + "\n(后面的课件文字太长,已截断)"
    return text


def has_video(path):
    if not path or not os.path.isfile(path) or not deps.find("ffprobe"):
        return False
    r = subprocess.run([deps.exe("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return "video" in r.stdout


def frames(task, root, media, tool, log):
    """本地视频抽帧 + OCR(+ 有课件时按课件定页码)。已有帧就不重抽(去重不幂等,重跑会删掉总结引用过的截图)"""
    if not has_video(media):
        return False
    if not deps.find("tesseract"):
        log("⚠️ 没装 tesseract,不读画面文字(macOS: brew install tesseract;Windows: winget install UB-Mannheim.TesseractOCR),只用文字稿")
        return False
    out = frames_dir(root, task["vid"])
    fresh = not glob.glob(os.path.join(glob.escape(out), "*.jpg"))
    steps = ([("extract_frames.py", [media, "12s", out]), ("dedup_frames.py", [out])] if fresh else []) + [("ocr_frames.py", [out])]
    pdfs = slide_pdfs(root)
    steps.append(("match_slides.py", [out, slides_dir(root)] if pdfs else [out, "--clear"]))
    for name, args in steps:
        r = tool(name, *args, root=root)
        log(f"== {name}: " + "\n".join((r.stdout + r.stderr).strip().splitlines()[-2:]))
        if r.returncode and name != "match_slides.py":
            log(f"⚠️ {name} 失败,这节课不用画面文字")
            if fresh:        # 没去重 / 没 OCR 完的帧删掉,下次重跑重新抽(去重不幂等,不能对旧帧补跑)
                shutil.rmtree(out, ignore_errors=True)
            return False
    log(f"== 画面 {len(glob.glob(os.path.join(glob.escape(out), '*.jpg')))} 张")
    return True
