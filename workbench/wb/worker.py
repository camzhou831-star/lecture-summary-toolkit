"""后台任务队列:一个线程按先后顺序处理排队的任务(whisper 和模型调用都重,一次只跑一个)。"""
import threading

from . import db, pipeline

_wake = threading.Event()
_stop = threading.Event()
_thread = None


def kick():
    _wake.set()


def _loop():
    while not _stop.is_set():
        tid = db.next_queued()
        if tid is None:
            _wake.wait(timeout=5)
            _wake.clear()
            continue
        pipeline.run_task(tid)


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
