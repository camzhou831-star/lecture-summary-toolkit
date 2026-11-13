#!/usr/bin/env python3
"""用课件 PDF 的文字给每一帧定页码(比 OCR 读工具栏 "N of M" 稳),写回 ocr.json 的 page/pages/deck/match 字段。
用法: match_slides.py <画面目录> <课件.pdf 或目录> [更多 pdf/目录...] [--min-score 0.35] [--dry-run]
      match_slides.py <画面目录> --clear      # 撤销匹配,恢复工具栏读到的页码
原理: pdftotext 逐页抽字 → 每帧 OCR 词集合与每页词集合算 相似度 = |A∩B| / |A|(A 为帧的词,偏向"帧上的字都能在这页找到")
      得分最高且 >= min-score 的页作为匹配;同分时优先与上一帧同一套课件、页码相近的。
      在超过一半课件页上都出现的词(页眉的单元代码/单元名等)两边都不计,少于 4 个有效词的帧不匹配,4–5 个词的帧要求 >= 0.6。
      OCR 读到的工具栏页码原样保存在 e["toolbar"]={"page","pages"}(只在第一次匹配时写入,重复匹配不会被 PDF 页码污染);
      匹配结果写 e["match"] 并覆盖 e["page"]/e["pages"]/e["deck"];--clear 从 e["toolbar"] 恢复。
      没有文字层的 PDF(扫描/图片版)会被识别并提示。课件按完整路径区分,不同目录同名 PDF 不会混。
依赖: poppler 的 pdftotext(brew install poppler);没有时用 Python 包 pypdf(Windows 上 py -m pip install pypdf)
"""
import argparse, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps
STOP = set("""the and for that this with are was were from into your you our can will not but have has had they them their which what when where how why
also than then there here these those such very just more most some any each other one two three four five six
been being does did done until now all its it's only over after before about between under through during while both same should would could may might must
next prev previous""".split())

def words(t):
    return set(w for w in re.findall(r"[a-z][a-z0-9'+-]{2,}", t.lower())) - STOP

def pdf_pages(path):
    if not deps.find("pdftotext"):
        try: import pypdf
        except ImportError: sys.exit(f"错误: 读课件需要 pdftotext 或 pypdf;安装: {deps.how('poppler')}")
        return [words(p.extract_text() or "") for p in pypdf.PdfReader(path).pages]
    r = subprocess.run([deps.exe("pdftotext"), "-layout", "-enc", "UTF-8", path, "-"], capture_output=True)
    if r.returncode != 0: sys.exit(f"错误: pdftotext 失败: {path}: {r.stderr.decode('utf-8','replace')[-200:]}")
    pages = r.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    return [words(p) for p in pages]

def deck_common(decks, frac=0.5, min_pages=4):
    """在所有课件页里出现率 > frac 的词(页眉的单元代码/单元名/"schedule" 之类),匹配时两边都去掉,免得标题帧靠页眉词配上任意一页"""
    pages = [pw for pgs in decks.values() for pw in pgs if pw]
    if len(pages) < min_pages: return set()
    df = {}
    for pw in pages:
        for w in pw: df[w] = df.get(w, 0) + 1
    return {w for w, n in df.items() if n > frac * len(pages)}

def collect_pdfs(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(os.path.join(a, f) for f in os.listdir(a) if f.lower().endswith(".pdf"))
        elif a.lower().endswith(".pdf"): out.append(a)
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--min-score", type=float, default=0.35); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    ocr_path = os.path.join(a.dir, "ocr.json")
    entries = json.load(open(ocr_path))
    if a.clear:
        n = 0
        for e in entries:
            if "toolbar" in e:
                e["page"], e["pages"] = e["toolbar"]["page"], e["toolbar"]["pages"]; n += 1
            e.pop("match", None); e.pop("deck", None)
        json.dump(entries, open(ocr_path, "w"), ensure_ascii=False, indent=1)
        print(f"== 已撤销课件匹配,恢复 {n} 帧的工具栏页码"); return
    pdfs = collect_pdfs(a.pdfs)
    if not pdfs: sys.exit("错误: 没有找到 PDF")
    decks = {}   # 完整路径 -> 各页词集合;显示名用不带扩展名的文件名
    for pth in pdfs:
        pages = pdf_pages(pth)
        if pages and not any(pages): print(f"   ⚠️ {os.path.basename(pth)} 没有文字层(扫描/图片版 PDF),无法用于匹配", file=sys.stderr); continue
        decks[pth] = pages
    if not decks: sys.exit("错误: 所有 PDF 都没有文字层")
    common = deck_common(decks)
    if common: decks = {d: [pw - common for pw in pgs] for d, pgs in decks.items()}
    prev = None; matched = 0; conflicts = 0
    for e in entries:
        if "toolbar" not in e: e["toolbar"] = {"page": e.get("page"), "pages": e.get("pages")}   # 只记录一次 OCR 原始结果
        tb_page = e["toolbar"]["page"]
        fw = words(e.get("text", "")) - common
        if len(fw) < 4: e["match"] = None; continue
        best = None
        for deck, pages in decks.items():
            for i, pw in enumerate(pages, 1):
                if not pw: continue
                score = len(fw & pw) / len(fw)
                bonus = 0.02 if prev and prev[0] == deck and abs(prev[1] - i) <= 2 else 0   # 连续性:同一套、相邻页优先
                if best is None or score + bonus > best[2]: best = (deck, i, score + bonus, score)
        need = a.min_score if len(fw) >= 6 else max(a.min_score, 0.6)    # 短文本帧要求更高的匹配度
        if best and best[3] >= need:
            deck, page, _, score = best
            if tb_page and tb_page != page: conflicts += 1
            name = os.path.splitext(os.path.basename(deck))[0]
            e["match"] = {"deck": name, "path": deck, "page": page, "pages": len(decks[deck]), "score": round(score, 2)}
            e["deck"] = name; e["page"] = page; e["pages"] = len(decks[deck]); matched += 1; prev = (deck, page)
        else:
            e["match"] = {"deck": None, "page": None, "score": round(best[3], 2) if best else 0}
            e["page"], e["pages"] = tb_page, e["toolbar"]["pages"]; e.pop("deck", None)
    if not a.dry_run: json.dump(entries, open(ocr_path, "w"), ensure_ascii=False, indent=1)
    print(f"== 课件匹配: {matched}/{len(entries)} 帧定到页码({len(decks)} 套课件),{conflicts} 帧与工具栏页码不一致(以 PDF 为准)" + (" (dry-run)" if a.dry_run else ""))

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace")   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()
