"""python -m wb [--port 8770] [--host 127.0.0.1]   端口也可以用环境变量 PORT 指定"""
import argparse
import os

import uvicorn


def main():
    ap = argparse.ArgumentParser(prog="wb", description="总结工作台(本地网页)")
    ap.add_argument("--host", default="127.0.0.1", help="只在本机打开;不要改成 0.0.0.0,除非你知道自己在做什么")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8770))
    a = ap.parse_args()
    print(f"== 总结工作台: http://{a.host}:{a.port}")
    uvicorn.run("wb.server:app", host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
