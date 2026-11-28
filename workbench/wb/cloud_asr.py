"""方言录播:用阿里云百炼的录音文件识别(paraformer-v2)转写,本机 whisper 认不了的方言走这里。

paraformer-v2 支持普通话和粤语、吴语、闽南语、四川话、东北话、上海话、湖南话、河南话等十多种方言,不用指定是哪种。
用户自己填百炼的 API Key(和 DeepSeek Key 一样是「自带 Key」)。按秒计费,新开通每月有免费额度。

流程:ffmpeg 把音频压成单声道 16 kHz 小 mp3 → 传到百炼的临时存储(48 小时后自动删)→ 提交转写任务 → 等结果 → 按句子写成 .srt。
录音会上传到阿里云,只在用户选了「方言」时才走这里。
"""
import os
import subprocess
import time

import httpx

from . import config

BASE = "https://dashscope.aliyuncs.com/api/v1"
MODEL = "paraformer-v2"
POLL_EVERY = 5
MAX_WAIT = 4 * 3600


class CloudASRError(Exception):
    pass


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _check(r, what):
    if r.status_code in (401, 403):
        raise CloudASRError("阿里云百炼 Key 不对或没开通语音识别:到「设置 → 方言识别」检查 Key")
    if r.status_code >= 400:
        try:
            j = r.json()
            msg = f"{j.get('code', '')} {j.get('message', '')}".strip()
        except ValueError:
            msg = r.text[:200]
        raise CloudASRError(f"{what}失败(HTTP {r.status_code}):{msg}")
    return r.json()


def check_key(key):
    """试一下 Key:拿一次上传凭证(不花钱)。不对就抛 CloudASRError"""
    with httpx.Client(timeout=20) as c:
        _check(c.get(f"{BASE}/uploads", params={"action": "getPolicy", "model": MODEL}, headers=_auth(key)), "验证 Key")


def compress(media, out):
    """单声道 16 kHz、32 kbps 的 mp3:三小时约 43 MB,上传快,识别不受影响"""
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode or not os.path.isfile(out):
        raise CloudASRError("抽音频失败:" + (r.stderr or "")[-300:])
    return out


def upload(c, key, path):
    """传到百炼临时存储 → oss:// 地址(48 小时有效)"""
    pol = _check(c.get(f"{BASE}/uploads", params={"action": "getPolicy", "model": MODEL}, headers=_auth(key)), "申请上传")["data"]
    size_mb = os.path.getsize(path) / 1e6
    limit = pol.get("max_file_size_mb")
    if limit and size_mb > float(limit):
        raise CloudASRError(f"音频压缩后 {size_mb:.0f} MB,超过阿里云单个文件上限 {limit} MB;可以把录播剪成几段再分别总结")
    obj = f"{pol['upload_dir']}/{os.path.basename(path)}"
    fields = {"OSSAccessKeyId": pol["oss_access_key_id"], "Signature": pol["signature"], "policy": pol["policy"],
              "x-oss-object-acl": pol["x_oss_object_acl"], "x-oss-forbid-overwrite": pol["x_oss_forbid_overwrite"],
              "key": obj, "success_action_status": "200"}
    with open(path, "rb") as f:
        r = c.post(pol["upload_host"], data=fields, files={"file": (os.path.basename(path), f, "audio/mpeg")}, timeout=1800)
    if r.status_code != 200:
        raise CloudASRError(f"上传音频失败(HTTP {r.status_code}):{r.text[:200]}")
    return "oss://" + obj


def submit(c, key, url):
    body = {"model": MODEL, "input": {"file_urls": [url]},
            "parameters": {"language_hints": ["zh", "yue", "en"], "timestamp_alignment_enabled": True}}
    h = dict(_auth(key), **{"X-DashScope-Async": "enable", "X-DashScope-OssResourceResolve": "enable"})
    j = _check(c.post(f"{BASE}/services/audio/asr/transcription", json=body, headers=h), "提交转写")
    return j["output"]["task_id"]


def wait(c, key, task_id, log, sleep=time.sleep):
    t0 = time.time()
    while True:
        out = _check(c.get(f"{BASE}/tasks/{task_id}", headers=_auth(key)), "查询转写进度")["output"]
        st = out.get("task_status")
        if st == "SUCCEEDED":
            res = (out.get("results") or [{}])[0]
            if res.get("subtask_status") not in (None, "SUCCEEDED"):
                raise CloudASRError(f"阿里云转写失败:{res.get('code', '')} {res.get('message', '')}".strip())
            return res["transcription_url"]
        if st in ("FAILED", "CANCELED", "UNKNOWN"):
            raise CloudASRError(f"阿里云转写失败:{out.get('code', st)} {out.get('message', '')}".strip())
        if time.time() - t0 > MAX_WAIT:
            raise CloudASRError("阿里云转写超过 4 小时还没出结果")
        log(f"   阿里云转写中…({st},已等 {int(time.time() - t0)} 秒)")
        sleep(POLL_EVERY if time.time() - t0 < 120 else 15)


def _ts(ms):
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(result, path):
    """识别结果 JSON → .srt(一句一条)。→ 条数"""
    sents = [s for t in result.get("transcripts") or [] for s in t.get("sentences") or [] if (s.get("text") or "").strip()]
    sents.sort(key=lambda s: s.get("begin_time", 0))
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(sents, 1):
            f.write(f"{i}\n{_ts(s['begin_time'])} --> {_ts(s['end_time'])}\n{s['text'].strip()}\n\n")
    return len(sents)


def transcribe(media, base, log, key=None):
    """本地音视频 → <base>.srt / <base>.txt"""
    key = key or config.dashscope_key()
    if not key:
        raise CloudASRError("选了「方言」要用阿里云百炼识别:先到「设置 → 方言识别」填阿里云百炼的 API Key")
    mp3 = base + ".cloud.mp3"
    log("== 方言识别:压缩音频后上传到阿里云百炼(paraformer-v2)")
    compress(media, mp3)
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as c:
            url = upload(c, key, mp3)
            log(f"== 已上传 {os.path.getsize(mp3) / 1e6:.1f} MB,开始转写")
            tid = submit(c, key, url)
            rurl = wait(c, key, tid, log)
            r = c.get(rurl)
            if r.status_code != 200:
                raise CloudASRError(f"下载识别结果失败(HTTP {r.status_code})")
            result = r.json()
    except httpx.HTTPError as e:
        raise CloudASRError(f"连不上阿里云百炼:{e}") from e
    finally:
        try:
            os.remove(mp3)
        except OSError:
            pass
    n = to_srt(result, base + ".srt")
    if not n:
        raise CloudASRError("阿里云没识别出文字(录音可能没有人声)")
    log(f"== 阿里云识别出 {n} 句")
    return n
