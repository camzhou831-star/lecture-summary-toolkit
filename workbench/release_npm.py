"""把当前提交打成 npm 包(工作台的「检查更新」从 npm / 国内 npmmirror 拿新版)。

    uv run python release_npm.py --zh "一句话说这版改了什么" --en "One line on what changed"
    npm publish ../dist/npm --access public        # 要先 npm login 一次

包里 app/ 下面就是仓库文件(git archive HEAD),不含根目录的启动文件(中英文包各有自己的名字,更新时不动它们)。
版本号取 workbench/VERSION,必须已经提交。
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "dist", "npm")
LAUNCHERS = {"启动工作台.command", "启动工作台.bat", "Start Workbench.command", "Start Workbench.bat"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zh", required=True)
    ap.add_argument("--en", required=True)
    a = ap.parse_args()
    ver = subprocess.run(["git", "show", "HEAD:workbench/VERSION"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    raw = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    shutil.rmtree(OUT, ignore_errors=True)
    app = os.path.join(OUT, "app")
    n = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if not m.isfile() or m.name in LAUNCHERS:
                continue
            dst = os.path.join(app, *m.name.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(tf.extractfile(m).read())
            os.chmod(dst, 0o755 if m.mode & 0o111 else 0o644)
            n += 1
    pkg = {"name": "lecture-summary-workbench", "version": ver,
           "description": "课程总结工作台 / Lecture Summary Workbench: update payload for the local app (not a JavaScript library).",
           "license": "MIT", "repository": {"type": "git", "url": "git+https://github.com/camzhou831-star/lecture-summary-toolkit.git"},
           "homepage": "https://github.com/camzhou831-star/lecture-summary-toolkit", "files": ["app/"],
           "workbench": {"notes": {"zh": a.zh, "en": a.en}}}
    json.dump(pkg, open(os.path.join(OUT, "package.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(OUT, "README.md"), "w", encoding="utf-8").write(
        "# lecture-summary-workbench\n\n课程总结工作台的更新包,由工作台的「检查更新」自动下载,不是 JavaScript 库。\n"
        "Update payload for Lecture Summary Workbench, downloaded by the app's built-in updater. Not a JavaScript library.\n\n"
        "https://github.com/camzhou831-star/lecture-summary-toolkit\n")
    print(f"== {OUT}:版本 {ver},{n} 个文件")


if __name__ == "__main__":
    main()
