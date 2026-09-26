"""课件 PDF 文字提取。
优先用 poppler 的 pdftotext(外部程序,GPL;我们只调用、不随工具分发它);没有时尝试 pypdf(BSD 许可,可选依赖);
都没有时给出能看懂的说明。不使用 PyMuPDF(AGPL,不适合随工具分发)。"""
import os, subprocess
from .util import which

class PdfError(Exception):
    def __init__(self, what, next_step):
        super().__init__(what); self.what = what; self.next_step = next_step

def backend():
    if which("pdftotext"): return "pdftotext"
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        return None

def extract_pages(path):
    """返回每页文字的列表(下标 0 = 第 1 页)"""
    b = backend()
    if b == "pdftotext":
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise PdfError(f"无法读取 PDF「{os.path.basename(path)}」:{err[-1] if err else '未知错误'}",
                           "确认文件能用预览/浏览器正常打开;如果 PDF 有密码,请先另存为无密码版本")
        pages = r.stdout.decode("utf-8", "replace").split("\f")
        if pages and not pages[-1].strip(): pages = pages[:-1]
        return pages
    if b == "pypdf":
        import pypdf
        try:
            reader = pypdf.PdfReader(path)
            return [(p.extract_text() or "") for p in reader.pages]
        except Exception as e:  # pypdf 对损坏文件抛各种异常
            raise PdfError(f"无法读取 PDF「{os.path.basename(path)}」:{e}", "确认文件能正常打开;有密码的 PDF 请先另存为无密码版本")
    raise PdfError("这台电脑上没有可用的 PDF 文字提取工具",
                   "Mac:在终端运行 brew install poppler;或者安装 Python 包 pypdf(pip install pypdf)。装好后点「重试」")

def text_status(pages):
    """ok / partial / none —— 判断是不是扫描版(没有文字层)"""
    n = len(pages)
    if n == 0: return "none"
    good = sum(1 for p in pages if len(p.strip()) >= 20)
    if good == 0: return "none"
    if good < n * 0.5: return "partial"
    return "ok"

def render_page(pdf, page, out_png, dpi=70):
    """把某一页渲染成图片(证据面板用);没有 pdftoppm 时返回 False,界面只显示文字"""
    if os.path.exists(out_png): return True
    if not which("pdftoppm"): return False
    prefix = out_png[:-4]
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    r = subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile", pdf, prefix], capture_output=True)
    return r.returncode == 0 and os.path.exists(out_png)
