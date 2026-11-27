"""选片数据(拉片流程第 1 节):这条视频和作者近 20 条比,算「相对值」。

  相对值 = 这条的点赞(取不到点赞就用播放)÷ 作者近 20 条的中位数。
  门槛照拉片流程:点赞 100+ 小爆款、1000+ 大爆款;不到 100 赞但相对值 ≥3 也能进参考池(小号的相对爆款)。

作者主页用 yt-dlp 列出来(--flat-playlist,只取列表不下视频)。B 站匿名访问作者主页常被拦(HTTP 412),
设置里选了「网站登录」的浏览器时会借它的登录状态;拿不到就如实写「未取到」和原因,不估。
"""
import json
import statistics
import subprocess

from . import sources

N = 20


def account_url(kind, meta):
    if kind == "bilibili" and meta.get("uploader_id"):
        return f"https://space.bilibili.com/{meta['uploader_id']}/video"
    if kind == "youtube":
        u = meta.get("channel_url") or meta.get("uploader_url")
        return (u.rstrip("/") + "/videos") if u else None
    return None


def list_videos(url, timeout=90):
    """作者最近 N 条:[(id, 播放, 点赞)];失败抛 RuntimeError(带原因)"""
    cmd = [sources.need("yt-dlp"), *sources.ytdlp_auth(), "--flat-playlist", "-J", "--playlist-end", str(N), url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("列作者作品超时")
    if r.returncode or not r.stdout.strip().startswith("{"):
        err = (r.stderr or "").strip().splitlines()[-1:] or ["未知错误"]
        if "412" in err[0] or "blocked" in err[0].lower():
            raise RuntimeError("B 站不让匿名看作者主页(412);在「设置 → 网站登录」选一个登录过 B 站的浏览器再重跑")
        raise RuntimeError("列作者作品失败:" + err[0][-160:])
    out = []
    for e in json.loads(r.stdout).get("entries") or []:
        if isinstance(e, dict):
            out.append((e.get("id"), e.get("view_count"), e.get("like_count")))
    return out


def stats(kind, meta, log):
    """→ dict:n、中位数、相对值、按什么算、说明。拿不到时只有 note"""
    url = account_url(kind, meta)
    if not url:
        return {"note": "这个来源没有作者主页信息"}
    try:
        vids = list_videos(url)
    except RuntimeError as e:
        log(f"⚠️ 相对值没算成:{e}")
        return {"note": str(e)}
    for key, idx, mine in (("点赞", 2, meta.get("like_count")), ("播放", 1, meta.get("view_count"))):
        vals = [v[idx] for v in vids if isinstance(v[idx], int)]
        if len(vals) >= 5 and isinstance(mine, int):
            med = statistics.median(vals)
            rel = round(mine / med, 2) if med else None
            log(f"== 作者近 {len(vals)} 条{key}中位数 {med:g},这条 {mine} → 相对值 {rel}")
            return {"n": len(vals), "by": key, "median": med, "rel": rel, "note": ""}
    return {"note": f"作者主页列出 {len(vids)} 条,但拿不到点赞 / 播放数"}


def tier(like, rel, lang="zh"):
    """参考池门槛(拉片流程 1 节)"""
    zh = lang == "zh"
    if isinstance(like, int) and like >= 1000:
        return "大爆款(1000+ 赞),优先拆" if zh else "big hit (1000+ likes), break it down first"
    if isinstance(like, int) and like >= 100:
        return "小爆款(100+ 赞),可进参考池" if zh else "small hit (100+ likes), fits the reference pool"
    if isinstance(rel, (int, float)) and rel >= 3:
        return "不到 100 赞,但相对值 ≥3(小号的相对爆款),可进参考池,要写明理由" if zh else "under 100 likes but relative value ≥3 (a small account's hit); fits the pool, note why"
    if isinstance(like, int):
        return "未过门槛(不到 100 赞、相对值不到 3),除非题材特别接近,一般不进参考池" if zh else "below the bar (under 100 likes, relative value under 3)"
    return "未取到" if zh else "n/a"
