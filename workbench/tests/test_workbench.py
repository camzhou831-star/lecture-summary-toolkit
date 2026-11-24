"""工作台基本测试:不联网、不需要 whisper 和模型 Key(模型调用用假的替换)。运行: cd workbench && uv run pytest -q
字幕素材在测试里现生成(仓库规定 .srt 不能放在 tests/ 和 examples/ 之外)。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_srt(n=40, step=15):
    blocks = []
    for i in range(n):
        s, e = i * step, i * step + step - 1
        ts = lambda x: f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d},000"
        blocks.append(f"{i + 1}\n{ts(s)} --> {ts(e)}\nSentence number {i} about gradient descent and learning rate.\n")
    return "\n".join(blocks)


GOOD = """# Gradient descent basics — 学习率

> 讲者:Test · 本讲没有课件页码

## ⚠️ 课程通知

无

## 一句话概括

梯度下降沿负梯度方向更新参数 [录播 00:00]。

## 核心要点

1. 学习率决定步长 [录播 01:00–02:15]。

## 章节时间线

- **[00:00] 开场** — 介绍梯度下降。
- **[05:00] 学习率** — 讲学习率的选择。

## 金句 / 考点信号

- "learning rate matters" [录播 05:00]

## 复习卡

梯度下降沿什么方向更新::负梯度方向
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WORKBENCH_NO_WORKER", "1")
    monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "none.json"))
    for k in ("DEEPSEEK_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import importlib
    from wb import config
    importlib.reload(config)
    from wb import db, llm, pipeline, server, sources
    for m in (db, sources, llm, pipeline, server):
        importlib.reload(m)
    db.init()
    srt = tmp_path / "Lecture 1.srt"
    srt.write_text(make_srt(), encoding="utf-8")
    return {"tmp": tmp_path, "srt": str(srt), "db": db, "pipeline": pipeline, "sources": sources, "server": server, "llm": llm}


# ---------- 链接识别 ----------
def test_parse_youtube(env):
    s = env["sources"]
    for url in ("https://www.youtube.com/watch?v=aircAruvnKk&list=x", "https://youtu.be/aircAruvnKk?si=1", "看这个 https://youtube.com/shorts/aircAruvnKk"):
        assert s.parse_source(url) == ("youtube", "aircAruvnKk", "https://www.youtube.com/watch?v=aircAruvnKk")


def test_parse_bilibili_with_share_text(env):
    s = env["sources"]
    kind, vid, url = s.parse_source("【机器学习】第1讲 https://www.bilibili.com/video/BV1Wv411h7kN/?spm_id_from=333&p=3 分享")
    assert (kind, vid, url) == ("bilibili", "BV1Wv411h7kN_p3", "https://www.bilibili.com/video/BV1Wv411h7kN?p=3")
    assert s.parse_source("https://www.bilibili.com/video/BV1Wv411h7kN")[1] == "BV1Wv411h7kN"


def test_parse_rejects(env):
    s = env["sources"]
    with pytest.raises(s.SourceError, match="抖音"):
        s.parse_source("https://v.douyin.com/abc/")
    with pytest.raises(s.SourceError, match="只支持"):
        s.parse_source("https://example.com/video")
    with pytest.raises(s.SourceError, match="找不到文件"):
        s.parse_source("/nope/x.mp4")


def test_parse_local(env):
    assert env["sources"].parse_source(env["srt"])[:2] == ("local", "Lecture_1")


def test_jump_url(env):
    s = env["sources"]
    assert s.jump_url("youtube", "https://www.youtube.com/watch?v=aircAruvnKk", 75) == "https://www.youtube.com/watch?v=aircAruvnKk&t=75s"
    assert s.jump_url("bilibili", "https://www.bilibili.com/video/BV1Wv411h7kN", 75).endswith("BV1Wv411h7kN?t=75")
    assert s.jump_url("bilibili", "https://www.bilibili.com/video/BV1Wv411h7kN?p=3", 75).endswith("?p=3&t=75")
    assert s.jump_url("local", "/x.mp4", 75) is None


def test_vtt_rolling_captions(env, tmp_path):
    vtt = tmp_path / "a.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello world\n\n00:00:03.000 --> 00:00:03.010\nhello world\n\n"
                   "00:00:03.010 --> 00:00:05.000\nhello world\nnext line\n", encoding="utf-8")
    out = tmp_path / "a.srt"
    assert env["sources"].vtt_to_srt(str(vtt), str(out)) == 2
    text = out.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:03,000\nhello world" in text and "next line" in text and text.count("hello world") == 1


def test_bilibili_download_sends_range_header(env, monkeypatch, tmp_path):
    """B 站 CDN 不带 Range 头会回 567(yt-dlp issue #17847);下载命令里必须带上"""
    s = env["sources"]
    seen = []

    def fake_run(cmd, log, timeout=0, env=None):
        seen.append(cmd)
        return 1, "HTTP Error 567: Unknown Status"
    monkeypatch.setattr(s, "run", fake_run)
    monkeypatch.setattr(s, "need", lambda c: c)
    task = {"kind": "bilibili", "source": "https://www.bilibili.com/video/BV1Wv411h7kN", "vid": "BV1Wv411h7kN", "lang": "auto"}
    with pytest.raises(s.SourceError, match="567"):
        s.fetch(task, str(tmp_path / "root"), lambda m: None)
    assert "Range:bytes=0-" in seen[0] and seen[0][seen[0].index("Range:bytes=0-") - 1] == "--add-header"


# ---------- 处理 ----------
def test_api_transcript_uses_mmss(env, tmp_path):
    p = env["pipeline"]
    g = tmp_path / "x.grounded.md"
    g.write_text("# x · 讲义稿\n\n> 时长\n> 每行 `[HH:MM]` 是…\n\n[00:00] hi\n\n[01:40] later\n", encoding="utf-8")
    b = tmp_path / "x.bundle.json"
    b.write_text('{"segments": [{"start": 3.2, "end": 5, "text": "hi"}, {"start": 6016.7, "end": 6020, "text": "later"}]}', encoding="utf-8")
    t = p.api_transcript(str(g), str(b))
    assert "[00:03] hi" in t and "[100:16] later" in t and "[HH:MM]" not in t


def test_link_timeline_only_in_timeline(env):
    p = env["pipeline"]
    task = {"kind": "youtube", "source": "https://www.youtube.com/watch?v=aircAruvnKk"}
    md = p.link_timeline(GOOD, task)
    assert "- **[05:00](<https://www.youtube.com/watch?v=aircAruvnKk&t=300s>) 学习率**" in md
    assert "1. 学习率决定步长 [录播 01:00–02:15]。" in md           # 核心要点不动
    assert p.link_timeline(md, task) == md                          # 幂等
    assert p.link_timeline(GOOD, {"kind": "local", "source": "/x.mp4"}) == GOOD


def test_system_prompt_contains_policy_and_headings(env):
    sp = env["pipeline"].system_prompt("en")
    assert "Review Cards" in sp and "写作规则(policy.md)" in sp and "{lang_hint}" not in sp


def test_pipeline_end_to_end_with_fake_model(env, monkeypatch):
    """本地 .srt → 整理 → (假)模型 → 加链接 + check_summary 通过"""
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    calls = []

    def fake_chat(messages, on_progress=None, **k):
        calls.append(messages)
        assert "[05:00]" in messages[1]["content"]          # 讲义稿用 [MM:SS] 标签
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done", t["log"]
    assert t["check_ok"] == 1, t["check_report"]
    assert set(t["timings"]) == {"fetch", "prepare", "summarize", "check"}
    assert len(calls) == 1
    assert os.path.exists(p.summary_path(t))


def test_pipeline_repairs_once_when_check_fails(env, monkeypatch):
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    bad = GOOD.replace("[05:00] 学习率", "[59:00] 学习率")      # 超出视频时长(10 分钟)
    replies = [bad, GOOD]

    def fake_chat(messages, on_progress=None, **k):
        if len(replies) == 1:
            assert "check_summary.py" in messages[-1]["content"] and "59:00" in messages[-1]["content"]
        return replies.pop(0), {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1 and not replies


def test_pipeline_without_key_fails_clearly(env):
    db, p = env["db"], env["pipeline"]
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "failed" and "Key" in t["message"] and t["stage"] == "summarize"
    assert "fetch" in t["timings"]                                   # 拿稿和整理已完成,配好 Key 重跑时直接复用


# ---------- 接口 ----------
def test_api(env):
    from fastapi.testclient import TestClient
    with TestClient(env["server"].app) as c:
        assert c.get("/api/config").json()["key_ok"] is False
        assert c.post("/api/tasks", json={"source": "https://v.douyin.com/x/"}).status_code == 400
        assert c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "out_lang": "fr"}).status_code == 400
        r = c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk"})
        assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["kind"] == "youtube"
        tid = r.json()["id"]
        assert c.get(f"/api/tasks/{tid}").json()["log"] == ""
        assert c.get(f"/api/tasks/{tid}/summary").status_code == 404
        r = c.post("/api/upload", files={"file": ("my talk.srt", make_srt(4).encode(), "text/plain")})
        assert r.status_code == 200 and r.json()["kind"] == "local"
        assert c.post("/api/upload", files={"file": ("x.exe", b"1", "application/octet-stream")}).status_code == 400
        assert [t["id"] for t in c.get("/api/tasks").json()][-1] == tid
        assert c.delete(f"/api/tasks/{tid}").json() == {"ok": True}
        assert c.get(f"/api/tasks/{tid}").status_code == 404
        assert "总结工作台" in c.get("/").text
