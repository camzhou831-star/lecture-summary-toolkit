"""语音模型按需下载(显示实际大小与进度、断点续传)+ 本机历史速度(用来粗略估计耗时)。
模型目录与 transcribe.sh 相同:WHISPER_MODEL_DIR 或 ~/.local/share/whisper-models。"""
import http.client, os, re, shutil, time, urllib.request, urllib.error
from .util import data_root, read_json, atomic_write_json

DEFAULT_MODEL = "large-v3-turbo"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
VAD_NAME = "ggml-silero-v5.1.2.bin"
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/" + VAD_NAME
# 只用于下载前的磁盘空间检查与界面提示;真实大小以下载时服务器返回的为准
SIZE_HINTS = {"large-v3-turbo": 1_650_000_000, "large-v3": 3_100_000_000, "medium": 1_530_000_000, "medium.en": 1_530_000_000,
              "small": 490_000_000, "small.en": 490_000_000, "base": 150_000_000, "base.en": 150_000_000, "tiny": 78_000_000, "tiny.en": 78_000_000}

class DownloadError(Exception):
    pass

def model_dir():
    return os.environ.get("WHISPER_MODEL_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "whisper-models")

def model_path(name):
    return os.path.join(model_dir(), f"ggml-{name}.bin")

def _meta_path(p):
    return p + ".lsk.json"

def present(name):
    """模型可用:下载时写了校验记录的,大小必须一致;没有记录的(以前手动/脚本下载的)大小至少为预估的一半才算可用"""
    p = model_path(name)
    if not os.path.exists(p): return False
    size = os.path.getsize(p)
    meta = read_json(_meta_path(p))
    if meta: return size == meta.get("size")
    return size >= SIZE_HINTS.get(name, 1_000_000) * 0.5

def size_hint(name):
    return SIZE_HINTS.get(name, 1_650_000_000)

def _expected_sha(headers):
    for k in ("X-Linked-Etag", "X-Xet-Hash", "ETag"):
        v = (headers.get(k) or "").strip('"').strip()
        if re.fullmatch(r"[0-9a-f]{64}", v): return v
    return None

def _download(url, dest, label, prog, log):
    """断点续传下载到 dest.part,校验通过后才改名为 dest;不完整/校验失败的文件永远不会出现在 dest。"""
    import hashlib
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:    # 服务器说已经没有剩余内容:不能确认完整,删掉重下
            os.remove(part)
            raise DownloadError(f"下载{label}的临时文件状态异常,已清除,请点「重试」重新下载")
        raise DownloadError(f"下载{label}失败:服务器返回 {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise DownloadError(f"下载{label}失败:网络连接不上({getattr(e, 'reason', e)})")
    if have and resp.status != 206:
        log("server ignored Range, restarting from 0"); have = 0        # 服务器不支持续传,从头下
    clen = resp.headers.get("Content-Length")
    total = int(clen) + have if clen else None
    sha_expected = _expected_sha(resp.headers)
    if total:
        free = shutil.disk_usage(os.path.dirname(dest)).free
        if free < (total - have) + 200_000_000:
            raise DownloadError(f"磁盘空间不够下载{label}:需要 {(total-have)/1e9:.1f} GB,只剩 {free/1e9:.1f} GB")
    h = hashlib.sha256()
    if have:
        with open(part, "rb") as f:
            for buf in iter(lambda: f.read(1 << 20), b""): h.update(buf)
    log(f"download {url} from {have} total={total} sha={'yes' if sha_expected else 'no'}")
    done = have; last = 0
    try:
        with open(part, "ab" if have else "wb") as f:
            while True:
                buf = resp.read(1 << 20)
                if not buf: break
                f.write(buf); h.update(buf); done += len(buf)
                if time.time() - last > 1:
                    last = time.time()
                    prog(f"下载{label}:{done/1e6:.0f} MB" + (f" / {total/1e6:.0f} MB" if total else ""), done, total)
    except (OSError, urllib.error.URLError, http.client.IncompleteRead) as e:
        raise DownloadError(f"下载{label}中断:{e}(已下载的 {done/1e6:.0f} MB 已保留,重试会接着下载)")
    if total and done < total:
        raise DownloadError(f"下载{label}没有完成({done/1e6:.0f}/{total/1e6:.0f} MB),重试会接着下载")
    if total and done > total:
        os.remove(part); raise DownloadError(f"下载{label}的大小不对,已删除临时文件,请重试")
    digest = h.hexdigest()
    if sha_expected and digest != sha_expected:
        os.remove(part); raise DownloadError(f"下载{label}的校验值不对(文件损坏),已删除,请重试")
    os.replace(part, dest)
    atomic_write_json(_meta_path(dest), {"size": done, "sha256": digest, "verified": "sha256" if sha_expected else ("size" if total else "none"), "url": url})

def ensure(name, prog, log=print, vad=True):
    os.makedirs(model_dir(), exist_ok=True)
    if not present(name):
        _download(MODEL_URL.format(name=name), model_path(name), f"语音识别模型 {name}", prog, log)
    else:
        prog(f"语音识别模型 {name} 已在本机", None, None)
    if not present(name):
        raise DownloadError(f"语音识别模型 {name} 文件不完整")
    vp = os.path.join(model_dir(), VAD_NAME)
    if vad and not (os.path.exists(vp) and os.path.getsize(vp) > 100_000):
        _download(VAD_URL, vp, "静音检测模型", prog, log)

# ---------- 本机历史速度 ----------

def _stats_path():
    return os.path.join(data_root(), "stats.json")

def record(stage, media_seconds, elapsed):
    if not media_seconds or media_seconds < 60: return
    s = read_json(_stats_path(), {}) or {}
    hist = s.setdefault(stage, [])
    hist.append(round(elapsed / media_seconds, 4)); del hist[:-5]
    atomic_write_json(_stats_path(), s)

def estimate(stage, media_seconds):
    """按最近几次的速度估算(秒);没有历史时返回 None。只是参考,不同视频、电脑负载都会影响。"""
    hist = (read_json(_stats_path(), {}) or {}).get(stage) or []
    if not hist or not media_seconds: return None
    hist = sorted(hist)
    return hist[len(hist) // 2] * media_seconds
