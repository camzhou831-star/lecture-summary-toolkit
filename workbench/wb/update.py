"""检查更新与一键更新。

新版发布在 npm(包名 lecture-summary-workbench),国内走阿里云的 npmmirror 镜像,不用翻墙;海外走 npm 官方源。
两个源都试,时区是 UTC+8(或 WORKBENCH_CN=1)时先试国内。

更新只换程序文件:
  - 不动 workbench/data(任务记录)、workbench/.venv、vendor/(Windows 的 whisper)、根目录的启动文件;
  - API Key、登录、语音模型都在别处,本来就不受影响;
  - 换之前把要被覆盖的旧文件备份到 .update-backup/<旧版本>/;换完先在新代码上试导入一次,失败就原样退回。
下载的包按镜像给的 sha512 校验。
"""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time

import httpx

from . import config

PKG = "lecture-summary-workbench"
REGISTRIES = {"cn": "https://registry.npmmirror.com", "global": "https://registry.npmjs.org"}
ROOT = config.TOOLKIT                                   # 解压出来的那个文件夹(课程总结工作台 / lecture-workbench)
VERSION_FILE = os.path.join(config.WB_DIR, "VERSION")
SKIP = ("workbench/data/", "workbench/.venv/", "vendor/", "examples/", ".update-backup/", ".git/")
LAUNCHERS = ("启动工作台.command", "启动工作台.bat", "Start Workbench.command", "Start Workbench.bat")
CHECK_EVERY = 6 * 3600

_cache = {"at": 0.0, "info": None}
_lock = threading.Lock()


class UpdateError(Exception):
    pass


def current():
    try:
        return open(VERSION_FILE, encoding="utf-8").read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def vtuple(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def prefer_cn():
    v = os.environ.get("WORKBENCH_CN")
    if v in ("0", "1"):
        return v == "1"
    return time.localtime().tm_gmtoff == 8 * 3600


def registries():
    if os.environ.get("WORKBENCH_UPDATE_REGISTRY"):          # 测试用:只用这一个源
        return [("test", os.environ["WORKBENCH_UPDATE_REGISTRY"].rstrip("/"))]
    order = ["cn", "global"] if prefer_cn() else ["global", "cn"]
    return [(k, REGISTRIES[k]) for k in order]


def _get(url, timeout=10):
    r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r


def check(force=False):
    """→ {"current", "latest", "newer", "notes", "tarball", "integrity", "source"};两个源都连不上 → {"current", "error"}"""
    with _lock:
        if not force and _cache["info"] and time.time() - _cache["at"] < CHECK_EVERY:
            return _cache["info"]
    cur, errors = current(), []
    for name, base in registries():
        try:
            j = _get(f"{base}/{PKG}/latest").json()
        except (httpx.HTTPError, ValueError) as e:
            errors.append(f"{name}: {str(e)[:120]}")
            continue
        latest = str(j.get("version") or "0.0.0")
        dist = j.get("dist") or {}
        info = {"current": cur, "latest": latest, "newer": vtuple(latest) > vtuple(cur),
                "notes": (j.get("workbench") or {}).get("notes") or {}, "tarball": dist.get("tarball"),
                "integrity": dist.get("integrity"), "source": name}
        with _lock:
            _cache.update(at=time.time(), info=info)
        return info
    return {"current": cur, "error": "两个更新源都连不上(" + ";".join(errors) + ")"}


def _verify(data, integrity):
    if not integrity or not integrity.startswith("sha512-"):
        raise UpdateError("更新包没有校验值,不装")
    want = base64.b64decode(integrity[len("sha512-"):])
    if hashlib.sha512(data).digest() != want:
        raise UpdateError("更新包校验不通过(下载不完整或被改过),没有装")


def _members(data):
    """解开 npm 包:只取 package/app/ 下面的普通文件 → {相对路径: (内容, 是否可执行)}"""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.startswith("package/app/"):
                continue
            rel = m.name[len("package/app/"):]
            if not rel or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
                raise UpdateError(f"更新包里有不安全的路径:{rel}")
            out[rel] = (tf.extractfile(m).read(), bool(m.mode & 0o111))
    if "workbench/VERSION" not in out or "workbench/wb/server.py" not in out:
        raise UpdateError("更新包内容不完整,没有装")
    return out


def _wanted(rel):
    return not rel.startswith(SKIP) and rel not in LAUNCHERS


def install(files, root=None, smoke=True):
    """把新文件写进 root;先备份旧文件,写完试导入,失败就退回。→ 新版本号"""
    root = root or ROOT
    old_ver = current() if root == ROOT else "old"
    backup = os.path.join(root, ".update-backup", old_ver)
    written, created = [], []
    try:
        for rel, (content, exe) in files.items():
            if not _wanted(rel):
                continue
            dst = os.path.join(root, *rel.split("/"))
            if os.path.isfile(dst):
                if open(dst, "rb").read() == content:
                    continue
                bak = os.path.join(backup, *rel.split("/"))
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(dst, bak)
                written.append((dst, bak))
            else:
                created.append(dst)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".update-tmp"
            with open(tmp, "wb") as f:
                f.write(content)
            if exe:
                os.chmod(tmp, 0o755)
            os.replace(tmp, dst)
        if smoke:
            _smoke(root)
    except Exception as e:
        for dst, bak in written:
            shutil.copy2(bak, dst)
        for dst in created:
            try:
                os.remove(dst)
            except OSError:
                pass
        raise UpdateError(f"更新没装成,已经退回原来的版本:{e}") from e
    return files["workbench/VERSION"][0].decode().strip()


def _smoke(root):
    """在新代码上试导入一次(用 uv,装上新依赖);导入失败说明新版在这台电脑上起不来"""
    wb = os.path.join(root, "workbench")
    uv = shutil.which("uv") or os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")
    cmd = [uv, "run", "python", "-c", "import wb.server"] if os.path.exists(uv) else [sys.executable, "-c", "import wb.server"]
    env = dict(os.environ, WORKBENCH_NO_WORKER="1")
    r = subprocess.run(cmd, cwd=wb, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, env=env)
    if r.returncode != 0:
        raise UpdateError("新版试启动失败:" + (r.stderr or r.stdout).strip()[-300:])


def apply(log=print):
    """下载最新版并装上 → 新版本号"""
    info = check(force=True)
    if info.get("error"):
        raise UpdateError(info["error"])
    if not info["newer"]:
        raise UpdateError(f"已经是最新版 {info['current']}")
    if not info.get("tarball"):
        raise UpdateError("更新源没给下载地址")
    log(f"== 下载新版 {info['latest']}(来源:{'国内镜像' if info['source'] == 'cn' else 'npm'})")
    try:
        data = _get(info["tarball"], timeout=180).content
    except httpx.HTTPError as e:
        raise UpdateError(f"下载更新失败:{e}") from e
    _verify(data, info.get("integrity"))
    ver = install(_members(data))
    with _lock:
        _cache.update(at=0.0, info=None)
    log(f"== 已更新到 {ver}")
    return ver


def restart_later(delay=1.5):
    """回完这次请求后重启服务(Mac / Linux 原地换进程,uv run 会顺手装上新依赖);Windows 让用户自己重开"""
    if os.name == "nt":
        return False
    uv = shutil.which("uv") or os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")
    if not os.path.exists(uv):
        return False

    def go():
        time.sleep(delay)
        os.chdir(config.WB_DIR)
        sys.stdout.flush(); sys.stderr.flush()
        os.execv(uv, [uv, "run", "python", "-m", "wb", *sys.argv[1:]])
    threading.Thread(target=go, daemon=True).start()
    return True
