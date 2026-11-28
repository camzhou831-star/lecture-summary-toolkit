"""后台任务队列:最多同时跑 config.parallel_tasks() 个任务(默认 2,设置里可改)。

转写、截帧这些本机重活由 heavy.py 的锁排着一个个来;写总结、审核这些调模型的步骤可以几个任务同时跑。
第 1 个任务在写总结时,第 2 个已经开始转写了。
"""
import threading

from . import config, db, pipeline

_wake = threading.Event()
_stop = threading.Event()
_thread = None
_running = set()
_rlock = threading.Lock()


def kick():
    _wake.set()


def _run(tid):
    try:
        pipeline.run_task(tid)
    finally:
        with _rlock:
            _running.discard(tid)
        _wake.set()


def _loop():
    while not _stop.is_set():
        with _rlock:
            free = len(_running) < config.parallel_tasks()
        tid = db.claim_next() if free else None
        if tid is None:
            _wake.wait(timeout=5)
            _wake.clear()
            continue
        with _rlock:
            _running.add(tid)
        threading.Thread(target=_run, args=(tid,), name=f"workbench-task-{tid}", daemon=True).start()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="workbench-worker", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    _wake.set()
