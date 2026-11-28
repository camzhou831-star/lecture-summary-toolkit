"""本机重活(下载 + whisper 转写、截帧 OCR、读课件、切镜机测)一次只让一个任务做。

几个任务可以同时跑(见 worker.py),但 whisper 这类活很吃 CPU / 内存,两个一起跑反而都慢;
调模型的步骤主要在等网络和推理,不受这把锁限制。
"""
import threading
from contextlib import contextmanager

from . import db

_lock = threading.Lock()


@contextmanager
def turn(task_id):
    if not _lock.acquire(blocking=False):
        db.update(task_id, message="等前一个任务转写完…")
        _lock.acquire()
    try:
        yield
    finally:
        _lock.release()
