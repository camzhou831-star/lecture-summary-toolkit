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


SLIDE_EXTS = (".pdf", ".pptx")


def slide_files(root):
    """任务目录里的课件:PDF 和 PowerPoint(.pptx)"""
    d = slides_dir(root)
    return sorted(f for f in glob.glob(os.path.join(glob.escape(d), "*")) if f.lower().endswith(SLIDE_EXTS))


def slide_pdfs(root):
    return [f for f in slide_files(root) if f.lower().endswith(".pdf")]


def _pptx_pages(path):
    """.pptx 逐页文字(不用装 PowerPoint / LibreOffice):按放映顺序读每页的文字,演讲者备注附在后面"""
    import re
    import zipfile
    from xml.etree import ElementTree as ET
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    try:
        z = zipfile.ZipFile(path)
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels")).iter(PR + "Relationship")}
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise RuntimeError(f"读不了 {os.path.basename(path)}(不是有效的 .pptx):{e}")
    names = set(z.namelist())

    def text_of(xml):
        out = []
        for para in ET.fromstring(xml).iter(A + "p"):
            line = "".join(t.text or "" for t in para.iter(A + "t")).strip()
            if line:
                out.append(line)
        return out

    pages = []
    for sid in pres.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"):
        target = rels.get(sid.get(R + "id"), "")
        name = "ppt/" + target.lstrip("/").removeprefix("ppt/")
        if name not in names:
            continue
        lines = text_of(z.read(name))
        srels = "ppt/slides/_rels/" + os.path.basename(name) + ".rels"          # 演讲者备注
        if srels in names:
            for r in ET.fromstring(z.read(srels)).iter(PR + "Relationship"):
                if r.get("Type", "").endswith("/notesSlide"):
                    nname = "ppt/" + re.sub(r"^(\.\./)+", "", r.get("Target", ""))
                    if nname in names:
                        notes = [l for l in text_of(z.read(nname)) if not l.isdigit()]   # 去掉备注页上的页码
                        if notes:
                            lines.append("(演讲者备注)" + " ".join(notes))
        pages.append("\n".join(lines))
    if not pages:
        raise RuntimeError(f"{os.path.basename(path)} 里没读到幻灯片")
    return pages


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


def read_pages(path):
    return _pptx_pages(path) if path.lower().endswith(".pptx") else _pdf_pages(path)


def page_count(root):
    """所有课件里最多的页数(只有课件的任务核对页码用)"""
    n = 0
    for f in slide_files(root):
        try:
            n = max(n, len(read_pages(f)))
        except RuntimeError:
            pass
    return n


def slides_text(root, log):
    """课件逐页文字,给写总结和审核用。没有课件返回空字符串"""
    out = []
    for pdf in slide_files(root):
        try:
            pages = read_pages(pdf)
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


# ---------- 课件里以图为主的页:截成图片,给能看图的模型写「图示解读」 ----------
PAGE_DIR = "页面"            # 课件/页面/p04.png
MAX_PAGE_IMAGES = 24
LOW_TEXT = 150               # 少于这么多字的页算「以图为主」


def page_images_dir(root):
    return os.path.join(slides_dir(root), PAGE_DIR)


def _pdf_content_pages(path):
    """PDF 里有「内容图」的页:pdfimages -list 列出每页的图,去掉每页都出现的背景 / 页眉图(同一对象出现在三成以上的页上)"""
    if not deps.find("pdfimages"):
        return set()
    r = subprocess.run([deps.exe("pdfimages"), "-list", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    rows = []
    for line in r.stdout.splitlines()[2:]:
        f = line.split()
        if len(f) >= 11 and f[2] == "image" and f[0].isdigit():
            rows.append((int(f[0]), f[10], int(f[3]) * int(f[4])))
    if not rows:
        return set()
    pages_of = {}
    for page, obj, _ in rows:
        pages_of.setdefault(obj, set()).add(page)
    total = max(p for p, _, _ in rows)
    return {page for page, obj, area in rows if area >= 120 * 120 and len(pages_of[obj]) <= max(2, total * 0.3)}


def page_images(root, log):
    """把以图为主的页存成图片(PDF 用 pdftoppm 渲染整页;.pptx 取该页里的图片),返回 [(页码, 图片路径)]。
    已经截过就直接用。没有 pdftoppm 时 PDF 跳过(只用文字)"""
    out_dir = page_images_dir(root)
    os.makedirs(out_dir, exist_ok=True)
    picked = []
    for f in slide_files(root):
        try:
            texts = read_pages(f)
        except RuntimeError:
            continue
        if f.lower().endswith(".pdf"):
            content = _pdf_content_pages(f)
            pages = [n for n in range(1, len(texts) + 1) if n in content or len(texts[n - 1].strip()) < LOW_TEXT]
            pages = sorted(pages, key=lambda n: (n not in content, len(texts[n - 1])))[:MAX_PAGE_IMAGES - len(picked)]
            if pages and not deps.find("pdftoppm"):
                log("⚠️ 没装 pdftoppm(poppler),课件里的图看不了,只用文字")
                continue
            for n in sorted(pages):
                dest = os.path.join(out_dir, f"p{n:02d}.png")
                if not os.path.isfile(dest):
                    subprocess.run([deps.exe("pdftoppm"), "-png", "-singlefile", "-scale-to", "1100", "-f", str(n), "-l", str(n), f, dest[:-4]],
                                   capture_output=True)
                if os.path.isfile(dest):
                    picked.append((n, dest))
        else:
            for n, path in _pptx_images(f, texts, out_dir)[:MAX_PAGE_IMAGES - len(picked)]:
                picked.append((n, path))
    if picked:
        log(f"== 课件里以图为主的页:{', '.join(dict.fromkeys('p%d' % n for n, _ in picked))}(已截成图,能看图的模型会看)")
    return picked


def _pptx_images(path, texts, out_dir):
    """.pptx:每页引用的图片(png / jpg / gif),只取「以图为主」或有图的页;同一张图出现在三成以上的页上(背景 / 页眉)不算"""
    import zipfile
    from xml.etree import ElementTree as ET
    PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    pres_rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels")).iter(PR + "Relationship")}
    pres = ET.fromstring(z.read("ppt/presentation.xml"))
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    slides = []
    for sid in pres.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"):
        name = "ppt/" + pres_rels.get(sid.get(R + "id"), "").lstrip("/").removeprefix("ppt/")
        if name in names:
            slides.append(name)
    media_of = []
    for name in slides:
        rels = "ppt/slides/_rels/" + os.path.basename(name) + ".rels"
        imgs = []
        if rels in names:
            for r in ET.fromstring(z.read(rels)).iter(PR + "Relationship"):
                if r.get("Type", "").endswith("/image"):
                    m = "ppt/media/" + os.path.basename(r.get("Target", ""))
                    if m in names and m.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and z.getinfo(m).file_size > 8000:
                        imgs.append(m)
        media_of.append(imgs)
    count = {}
    for imgs in media_of:
        for m in set(imgs):
            count[m] = count.get(m, 0) + 1
    out = []
    for n, imgs in enumerate(media_of, 1):
        imgs = [m for m in dict.fromkeys(imgs) if count[m] <= max(2, len(slides) * 0.3)]
        if not imgs or (n <= len(texts) and len(texts[n - 1].strip()) >= 600):   # 字很多的页,图多半是配图,不看
            continue
        for k, m in enumerate(imgs[:2], 1):
            dest = os.path.join(out_dir, f"p{n:02d}-{k}{os.path.splitext(m)[1].lower()}")
            if not os.path.isfile(dest):
                open(dest, "wb").write(z.read(m))
            out.append((n, dest))
    return out
