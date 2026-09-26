"""公共工具:目录位置、原子写入、指纹、路径脱敏。"""
import hashlib, json, os, re, sys, tempfile, time

TOOLKIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(TOOLKIT, "工具")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
VERSION = "web-v1.0"

def data_root():
    """工作台数据目录:默认 <工具仓库>/工作台数据,可用环境变量 LSK_DATA 覆盖。不在 git 里。"""
    d = os.environ.get("LSK_DATA") or os.path.join(TOOLKIT, "工作台数据")
    os.makedirs(d, exist_ok=True)
    return d

def atomic_write_text(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try: os.remove(tmp)
        except OSError: pass
        raise

def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return default
    except (json.JSONDecodeError, UnicodeDecodeError): return default

def file_fingerprint(path):
    """大文件不整体算哈希:大小 + 修改时间 + 头尾各 1 MB 的 sha1。足以识别"换了文件/文件被改过"。"""
    st = os.stat(path)
    h = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if st.st_size > 2 << 20:
            f.seek(-(1 << 20), os.SEEK_END); h.update(f.read(1 << 20))
    return h.hexdigest()[:16]

def fingerprint(*parts):
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]

def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def hms(sec):
    sec = int(round(sec or 0))
    return f"{sec//3600}:{sec%3600//60:02d}:{sec%60:02d}" if sec >= 3600 else f"{sec//60:02d}:{sec%60:02d}"

def redact(text):
    """诊断信息脱敏:用户目录换成 ~,其余绝对路径只留文件名。"""
    if not text: return text
    home = os.path.expanduser("~")
    text = text.replace(home, "~")
    return re.sub(r"(?:(?:[A-Za-z]:)?[\\/][^\s\"'<>|]*[\\/])([^\\/\s\"'<>|]+)", r"…/\1", text)

def which(cmd):
    from shutil import which as w
    return w(cmd)

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
