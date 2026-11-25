"""输入层:链接或本地文件 → 课程视频/<名>.srt + meta.json + 来源.txt

拿稿逻辑照搬拉片流程的 ~/个人自媒体/tools/script_fetch.py(11-20 版,Windows 原件,这里是复制不是 import,原文件不改):
  B站     -> yt-dlp 匿名只拿音频 + 作品数据 -> whisper 转写
  YouTube -> yt-dlp 直接下字幕(多半是自动字幕),不转写;没有字幕时退回 下音频 + whisper
  本地    -> .srt/.vtt 直接用;视频 / 音频 -> whisper 转写
  抖音    -> 第二期再接(匿名下载会被限流)
与原件的区别:whisper 不再写死 Windows 的 whisper-cli.exe,改调录播课工具自己的 工具/transcribe.py
(按系统找 whisper-cli:Mac 是 /opt/homebrew/bin/whisper-cli;带 VAD 静音检测和 GPU 失败回退)。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

from . import config

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg")
SUB_EXTS = (".srt", ".vtt")
# B 站 CDN 对不带 Range 头的下载返回 HTTP 567(yt-dlp issue #17847,2026-11 仍未修);
# 照 issue 里给的临时解法带上 Range: bytes=0-(浏览器播放时也发这个头),yt-dlp 修好后可删
BILI_DL_ARGS = ["--add-header", "Range:bytes=0-"]
META_KEYS = ["id", "title", "uploader", "duration", "upload_date", "view_count", "like_count", "comment_count", "webpage_url", "language"]


class SourceError(Exception):
    """给用户看的失败原因(附退路:自己下载再拖进来)"""


# ---------- 链接识别 ----------
def parse_source(text):
    """返回 (kind, vid, 规范链接或文件路径);认不出时抛 SourceError"""
    s = (text or "").strip()
    if not s:
        raise SourceError("没有填链接或文件路径")
    m = re.search(r"https?://\S+", s)          # 分享文案里夹着链接(B 站 / 抖音常见)
    url = m.group(0) if m else s
    low = url.lower()
    if "douyin.com" in low or "iesdouyin.com" in low:
        raise SourceError("抖音链接第二期再接(匿名下载会被限流)。现在可以先自己下载视频,再把文件拖进来。")
    if "b23.tv" in low:
        url = resolve_redirect(url)
        low = url.lower()
    if "bilibili.com" in low:
        m = re.search(r"(BV[0-9A-Za-z]{10})", url)
        if not m:
            raise SourceError("B 站链接里认不出 BV 号")
        p = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("p", [None])[0]
        canon = f"https://www.bilibili.com/video/{m.group(1)}" + (f"?p={p}" if p and p != "1" else "")
        return "bilibili", m.group(1) + (f"_p{p}" if p and p != "1" else ""), canon
    if "youtube.com" in low or "youtu.be" in low:
        m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})", url)
        if not m:
            raise SourceError("YouTube 链接里认不出视频 id")
        return "youtube", m.group(1), f"https://www.youtube.com/watch?v={m.group(1)}"
    if low.startswith(("http://", "https://")):   # 其它网站:Twitch、Vimeo、TED、Kaltura、Panopto……都交给 yt-dlp 试
        u = urllib.parse.urlparse(url)
        host = (u.hostname or "web").removeprefix("www.")
        tail = re.sub(r"[^0-9A-Za-z]+", "_", (u.path + ("_" + u.query if u.query else "")).strip("/"))[-40:].strip("_")
        return "web", safe(f"{host.split('.')[0]}_{tail}" if tail else host), url
    path = os.path.expanduser(s.strip("'\""))
    if not os.path.isfile(path):
        raise SourceError(f"找不到文件 {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTS + SUB_EXTS:
        raise SourceError(f"不支持的文件类型 {ext}(支持视频、音频、.srt、.vtt)")
    return "local", safe(os.path.splitext(os.path.basename(path))[0]), os.path.abspath(path)


def resolve_redirect(url):
    import httpx
    try:
        r = httpx.head(url, follow_redirects=True, timeout=15)
        return str(r.url)
    except httpx.HTTPError as e:
        raise SourceError(f"短链接打不开: {e}") from e


def safe(s):
    return re.sub(r'[\\/:*?"<>|#\s]+', "_", s).strip("_")[:40] or "untitled"


def jump_url(kind, source, sec):
    """原视频在第 sec 秒的地址(回跳用)"""
    sec = int(sec)
    if kind == "youtube":
        return f"{source}&t={sec}s"
    if kind == "bilibili":
        return source + ("&" if "?" in source else "?") + f"t={sec}"
    if kind == "web":
        low = source.lower()
        if "twitch.tv/videos/" in low:              # Twitch 回放:?t=1h2m3s
            return source.split("#")[0] + ("&" if "?" in source else "?") + f"t={sec // 3600}h{sec % 3600 // 60}m{sec % 60}s"
        if "vimeo.com/" in low:                     # Vimeo:#t=123s
            return source.split("#")[0] + f"#t={sec}s"
        return source.split("#")[0] + f"#t={sec}"  # 其它网站:HTML5 媒体片段语法,不保证每个网站都认
    return None


SITE_NAMES = {"twitch": "Twitch", "vimeo": "Vimeo", "ted": "TED", "kaltura": "Kaltura", "panopto": "Panopto", "khanacademy": "Khan Academy",
              "coursera": "Coursera", "udemy": "Udemy", "edx": "edX", "echo360": "Echo360", "yuja": "YuJa", "zoom": "Zoom", "loom": "Loom", "soundcloud": "SoundCloud", "archive.org": "Internet Archive", "dailymotion": "Dailymotion"}


def site_name(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return next((v for k, v in SITE_NAMES.items() if k in host), host.removeprefix("www.") or "网页")


# ---------- 文本格式(照搬 script_fetch.py) ----------
def vtt_to_srt(vtt, srt):
    """YouTube 自动字幕是滚动的,同一句会重复出现;只保留每个时间块里新出现的那一行。"""
    out, last, n = [], "", 0
    for block in re.split(r"\r?\n\r?\n", open(vtt, encoding="utf-8", errors="replace").read()):
        rows = block.strip().splitlines()
        t = next((r for r in rows if "-->" in r), None)
        if not t:
            continue
        text = [re.sub(r"<[^>]+>", "", r).strip() for r in rows[rows.index(t) + 1:]]
        text = [x for x in text if x and x != last]
        if not text:
            continue
        a, b = [x.strip().split(" ")[0].replace(".", ",") for x in t.split("-->")]
        if a.count(":") == 1:
            a = "00:" + a
        if b.count(":") == 1:
            b = "00:" + b
        if a == b or (len(text) == 1 and b[:8] == a[:8] and abs(int(b[-3:]) - int(a[-3:])) <= 20):
            continue
        last = text[-1]
        n += 1
        out.append(f"{n}\n{a} --> {b}\n{' '.join(text)}\n")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return n


def srt_to_txt(srt, txt):
    lines = []
    for block in re.split(r"\r?\n\r?\n", open(srt, encoding="utf-8", errors="replace").read()):
        rows = [r for r in block.strip().splitlines() if r.strip()]
        text = [r for r in rows if not r.strip().isdigit() and "-->" not in r]
        if text:
            lines.append(" ".join(text))
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


# ---------- 外部命令 ----------
def run(cmd, log, timeout=3600, env=None):
    """跑命令,输出逐行写进任务日志;返回 (退出码, 最后 2000 字输出)"""
    log("$ " + " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    tail = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         env=dict(os.environ, PYTHONUTF8="1", **(env or {})))
    try:
        for line in p.stdout:
            line = line.rstrip()
            if line and not re.match(r"^\[download\]\s+\d", line):     # yt-dlp 的下载百分比刷屏,不进日志
                log(line)
            tail.append(line)
            tail[:] = tail[-40:]
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return 124, "超时"
    return p.returncode, "\n".join(tail)[-2000:]


def ytdlp_auth():
    """设置里选了「用浏览器登录状态」时,让 yt-dlp 读这个浏览器的 cookie(只在本机用,不上传)"""
    b = config.cookies_browser()
    return ["--cookies-from-browser", b] if b else []


LOGIN_HINT = ("这个网站可能要登录才能看(学校的 Panopto / Echo360 / Kaltura、Coursera、Udemy 常见)。"
              "可以在「设置 → 网站登录」里选你登录过的浏览器再重跑,或者自己下载后选文件。")


def need(cmd):
    sys.path.insert(0, config.TOOLS)
    import deps                                     # 录播课工具的找程序逻辑(Windows 上还查常见安装位置)
    p = deps.find(cmd)
    if not p:
        raise SourceError(f"找不到 {cmd};安装: {deps.how(cmd) if cmd in deps.INSTALL else 'brew install ' + cmd}")
    return p


def save_meta(info_path, meta_path):
    if not os.path.exists(info_path):
        return {}
    j = json.load(open(info_path, encoding="utf-8"))
    meta = {k: j.get(k) for k in META_KEYS}
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.remove(info_path)
    return meta


def transcribe(media, base, lang, log):
    """调录播课工具的 transcribe.py:产出 <base>.srt / <base>.txt"""
    need("ffmpeg")
    need("whisper-cli")
    code, tail = run([sys.executable, os.path.join(config.TOOLS, "transcribe.py"), media, lang], log, timeout=4 * 3600,
                     env={"OUT_BASE": base})
    if code or not os.path.exists(base + ".srt"):
        raise SourceError("转写失败:" + tail[-300:])


# ---------- 拿稿 ----------
def fetch(task, root, log):
    """把任务的来源变成 <root>/课程视频/<名>.srt。返回 (srt 路径, meta dict)。已有 srt 时直接用"""
    kind, source, name = task["kind"], task["source"], task["vid"]
    vdir = os.path.join(root, "课程视频")
    os.makedirs(vdir, exist_ok=True)
    base = os.path.join(vdir, name)
    srt = base + ".srt"
    meta_path = os.path.join(root, "meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    if os.path.exists(srt) and os.path.getsize(srt) > 0:
        log("== 已有文字稿,跳过拿稿")
        return srt, meta
    lang = task["lang"]
    if kind == "bilibili":
        need("yt-dlp")
        code, tail = run([need("yt-dlp"), *ytdlp_auth(), "-f", "ba", "--no-playlist", *BILI_DL_ARGS, "--write-info-json", "-o", os.path.join(vdir, "src.%(ext)s"), source],
                         log, timeout=1800)
        src = [f for f in glob.glob(os.path.join(vdir, "src.*")) if not f.endswith(".json")]
        if not src:
            why = "B 站 CDN 拒绝了下载(HTTP 567,见 yt-dlp issue #17847)" if "567" in tail else "B 站音频没下载下来(可能限流、需要登录或是付费视频)"
            raise SourceError(why + "。可以自己下载后选文件。\n" + tail[-300:])
        meta = save_meta(os.path.join(vdir, "src.info.json"), meta_path)
        transcribe(src[0], base, "zh" if lang == "auto" else lang, log)
        os.remove(src[0])
        how = "yt-dlp 匿名音频 + whisper large-v3-turbo 转写,时间精度约 ±0.5 秒,同音错字未校"
    elif kind == "youtube":
        need("yt-dlp")
        sub = "en" if lang == "auto" else lang
        code, tail = run([need("yt-dlp"), *ytdlp_auth(), "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", sub, "--sub-format", "vtt",
                          "--write-info-json", "-o", os.path.join(vdir, "src.%(ext)s"), source], log, timeout=600)
        meta = save_meta(os.path.join(vdir, "src.info.json"), meta_path)
        vtts = sorted(glob.glob(os.path.join(vdir, "src.*.vtt")))
        if vtts and vtt_to_srt(vtts[0], srt) > 0:
            how = "yt-dlp 下的 YouTube 字幕(多半是自动字幕),断句是平台切的,时间精度约 ±1 秒"
        else:
            log(f"== 没有 {sub} 字幕,改为下载音频 + whisper 转写")
            code, tail = run([need("yt-dlp"), *ytdlp_auth(), "-f", "ba", "--no-playlist", "-o", os.path.join(vdir, "src.%(ext)s"), source], log, timeout=1800)
            src = [f for f in glob.glob(os.path.join(vdir, "src.*")) if not f.endswith((".json", ".vtt"))]
            if not src:
                raise SourceError("YouTube 字幕和音频都没拿到(可能限流或需要登录)。可以自己下载后把文件拖进来。\n" + tail[-300:])
            transcribe(src[0], base, "auto" if lang == "auto" else lang, log)
            os.remove(src[0])
            how = "yt-dlp 音频 + whisper large-v3-turbo 转写,时间精度约 ±0.5 秒,同音错字未校"
        for v in vtts:
            os.remove(v)
    elif kind == "web":
        yt = need("yt-dlp")
        sub = "en,en-US,en-GB,en-orig" if lang in ("auto", "en") else f"{lang},{lang}-Hans,{lang}-CN"
        code, tail = run([yt, *ytdlp_auth(), "--no-playlist", "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", sub,
                          "--sub-format", "vtt/best", "--convert-subs", "vtt", "--write-info-json", "-o", os.path.join(vdir, "src.%(ext)s"), source], log, timeout=600)
        if code and not os.path.exists(os.path.join(vdir, "src.info.json")):
            if "Unsupported URL" in tail:
                raise SourceError("yt-dlp 不认识这个网页(网页里可能没有视频,或者视频藏在播放器框里)。可以打开视频所在的页面再复制链接,或者下载后选文件。")
            raise SourceError(("拿不到视频信息。" + LOGIN_HINT) if re.search(r"login|log in|sign in|401|403|cookies|private|members", tail, re.I)
                              else "拿不到视频信息:" + tail[-300:])
        meta = save_meta(os.path.join(vdir, "src.info.json"), meta_path)
        meta["site"] = site_name(source)
        vtts = sorted(glob.glob(os.path.join(vdir, "src.*.vtt")))
        if vtts and vtt_to_srt(vtts[0], srt) > 0:
            how = f"yt-dlp 下的 {meta['site']} 字幕,时间精度约 ±1 秒"
        else:
            log("== 网页没有现成字幕,下载音频用 whisper 转写")
            code, tail = run([yt, *ytdlp_auth(), "--no-playlist", "-f", "ba/b", "-o", os.path.join(vdir, "src.%(ext)s"), source], log, timeout=4 * 3600)
            src = [f for f in glob.glob(os.path.join(vdir, "src.*")) if not f.endswith((".json", ".vtt", ".part"))]
            if not src:
                raise SourceError("音频没下载下来。" + LOGIN_HINT + "\n" + tail[-300:])
            transcribe(src[0], base, lang, log)
            os.remove(src[0])
            how = f"yt-dlp 下 {meta['site']} 音频 + whisper large-v3-turbo 转写,时间精度约 ±0.5 秒,同音错字未校"
        for v in vtts:
            os.remove(v)
    elif kind == "local":
        ext = os.path.splitext(source)[1].lower()
        meta = {"title": os.path.splitext(os.path.basename(source))[0], "media_path": source if ext in VIDEO_EXTS else None}
        if ext == ".vtt":
            vtt_to_srt(source, srt)
            how = "本地 .vtt 字幕"
        elif ext == ".srt":
            shutil.copyfile(source, srt)
            how = "本地 .srt 字幕"
        else:
            stem = os.path.splitext(source)[0]
            side = next((stem + e for e in (".srt", ".vtt") if os.path.isfile(stem + e) and os.path.getsize(stem + e) > 0), None)
            if side:      # 视频旁边有同名字幕(学校录播常一起给,或之前转写过):直接用,不再转写
                (shutil.copyfile if side.endswith(".srt") else vtt_to_srt)(side, srt)
                how = f"视频旁边的同名字幕 {os.path.basename(side)}"
                log(f"== 用视频旁边的同名字幕 {os.path.basename(side)},不再转写")
            else:
                transcribe(source, base, lang, log)
                how = "本地文件 + whisper large-v3-turbo 转写,时间精度约 ±0.5 秒,同音错字未校"
            meta["duration"] = media_duration(source)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
    else:
        raise SourceError(f"不认识的来源类型 {kind}")
    if not os.path.exists(srt) or os.path.getsize(srt) == 0:
        raise SourceError("没拿到文字稿")
    n = srt_to_txt(srt, base + ".txt")
    meta["how"] = how
    meta["lines"] = n
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    with open(os.path.join(root, "来源.txt"), "w", encoding="utf-8") as f:
        f.write(f"平台:{kind}\n链接:{source}\n来源方式和精度:{how}\n")
    log(f"== 文字稿 {n} 句({how})")
    if n < 5:
        log(f"⚠️ 只有 {n} 句:可能没有口播,或是 whisper 编的,要手核")
    return srt, meta


def media_duration(path):
    try:
        r = subprocess.run([need("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except (SourceError, ValueError, subprocess.SubprocessError):
        return None
