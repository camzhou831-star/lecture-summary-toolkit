"""工作台基本测试:不联网、不需要 whisper 和模型 Key(模型调用用假的替换)。运行: cd workbench && uv run pytest -q
字幕素材在测试里现生成(仓库规定 .srt 不能放在 tests/ 和 examples/ 之外)。
"""
import json
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
    monkeypatch.setenv("WORKBENCH_PROVIDER", "api")          # 测试不去调本机的 claude / codex
    monkeypatch.delenv("WORKBENCH_COOKIES_BROWSER", raising=False)
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
    with pytest.raises(s.SourceError, match="找不到文件"):
        s.parse_source("/nope/x.mp4")


def test_parse_other_sites_go_to_ytdlp(env):
    s = env["sources"]
    kind, vid, url = s.parse_source("https://www.twitch.tv/videos/2345678901")
    assert (kind, url) == ("web", "https://www.twitch.tv/videos/2345678901") and vid == "twitch_videos_2345678901"
    assert s.parse_source("https://vimeo.com/76979871")[0] == "web"
    assert s.site_name("https://uwa.au.panopto.com/Panopto/Pages/Viewer.aspx?id=x") == "Panopto"


def test_jump_url_web(env):
    s = env["sources"]
    assert s.jump_url("web", "https://www.twitch.tv/videos/1", 3725) == "https://www.twitch.tv/videos/1?t=1h2m5s"
    assert s.jump_url("web", "https://vimeo.com/76979871", 75) == "https://vimeo.com/76979871#t=75s"


def test_cookies_browser_only_when_chosen(env, tmp_path, monkeypatch):
    s, cfg = env["sources"], __import__("wb.config", fromlist=["x"])
    assert s.ytdlp_auth() == []
    cfg.save_setting("cookies_browser", "chrome")
    assert s.ytdlp_auth() == ["--cookies-from-browser", "chrome"]
    cfg.save_setting("cookies_browser", "../evil")
    assert s.ytdlp_auth() == []
    assert oct(os.stat(cfg.CONFIG_FILE).st_mode & 0o777) == "0o600"


def test_cli_provider_flatten_and_auto(env, monkeypatch):
    llm = env["llm"]
    sys_, prompt = llm._flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}])
    assert (sys_, prompt) == ("S", "U")
    _, prompt = llm._flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                              {"role": "assistant", "content": "A"}, {"role": "user", "content": "FIX"}])
    assert "你上一次的回答" in prompt and prompt.index("A") < prompt.index("FIX")
    monkeypatch.setenv("WORKBENCH_PROVIDER", "auto")
    monkeypatch.setattr(llm, "available", lambda: {"api": (False, ""), "claude": (False, ""), "codex": (True, "/x/codex")})
    assert llm.resolve() == "codex"
    monkeypatch.setattr(llm, "available", lambda: {"api": (False, ""), "claude": (False, ""), "codex": (False, "")})
    with pytest.raises(llm.LLMError, match="Claude Code 或 Codex"):
        llm.resolve()


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


def test_duration_not_written_as_timestamp(env):
    """时长写成 MM:SS 会被模型照抄进引用块,check_summary 当成时间戳判"超出时长"(英文实测踩过)"""
    task = {"kind": "youtube", "source": "x", "vid": "x", "out_lang": "en"}
    up = env["pipeline"].user_prompt(task, {"duration": 1120}, "")
    assert "18 分 40 秒" in up and "18:40" not in up


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
            assert "检查结果" in messages[-1]["content"] and "59:00" in messages[-1]["content"]
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
        cj = c.get("/api/config").json()
        assert cj["key_ok"] is False and {p["id"] for p in cj["providers"]} == {"claude", "codex", "api"}
        assert c.post("/api/config/provider", json={"provider": "nope"}).status_code == 400
        assert c.post("/api/config/provider", json={"provider": "codex"}).status_code == 200
        from wb import config as cfg
        assert cfg._file_config()["provider"] == "codex"          # 写进配置文件(测试里环境变量优先,所以看文件)
        assert c.post("/api/config/cookies", json={"browser": "netscape"}).status_code == 400
        st = c.get("/api/status").json()
        assert {t["name"] for t in st["tools"]} >= {"yt-dlp", "ffmpeg", "whisper-cli"} and st["counts"] == {}
        assert {"platform", "brew", "npm", "model_ready", "workbench_dir"} <= set(st) and st["workbench_dir"].endswith("workbench")
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


# ---------- 中英双语 ----------
def test_i18n_keys_exist_in_both_languages():
    """页面(data-i18n*)和 JS(t("..."))用到的词条,中英两套都要有;用 node 读 i18n.js 的词典,没有 node 就跳过"""
    import json, re, shutil, subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node")
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wb", "static")
    i18n = os.path.join(static, "i18n.js")
    out = subprocess.run([node, "-e", f"eval(require('fs').readFileSync({json.dumps(i18n)}, 'utf8') + ';globalThis.D=I18N'); "
                          "console.log(JSON.stringify({zh: Object.keys(D.zh), en: Object.keys(D.en)}))"],
                         capture_output=True, text=True, env=dict(os.environ, LANG="C"))
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert set(d["zh"]) == set(d["en"]), set(d["zh"]) ^ set(d["en"])
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r'data-i18n(?:-ph|-title|-html)?="([\w]+)"', html))
    used |= {k for k in re.findall(r'\bt\("(\w+)"', js) if not k.endswith("_")}   # "kind_" + k 这类动态拼接的前缀不算
    used |= {"st_" + k for k in ("fetch", "prepare", "summarize", "check")} | {"kind_" + k for k in ("youtube", "bilibili", "local", "web")}
    missing = sorted(k for k in used if k not in d["zh"])
    assert not missing, missing


# ---------- 对标拆稿 / 会议纪要 ----------
def short_srt(tmp_path):
    p = tmp_path / "short.srt"
    p.write_text("1\n00:00:00,000 --> 00:00:12,000\n你知道吗?九成的人都用错了。今天教你三步。\n\n"
                 "2\n00:00:12,000 --> 00:00:30,000\n第一步打开设置,第二步找到隐私,第三步关掉追踪。我自己试过,一周省了两小时。\n\n"
                 "3\n00:00:30,000 --> 00:00:36,000\n关注我,下期讲更多。\n", encoding="utf-8")
    return str(p)


def test_breakdown_sentences_and_stats(env, tmp_path):
    from wb import breakdown as b
    subs = b.sentences(short_srt(tmp_path))
    assert [x[2] for x in subs][:3] == ["你知道吗?", "九成的人都用错了。", "今天教你三步。"]
    assert abs(subs[-1][1] - 36) < 0.01 and all(x[1] >= x[0] for x in subs)
    assert b.count("用 AI 做 3 个 demo") == 6                      # 汉字各 1,英文词和数字各算 1
    segs = [{"from": 1, "to": 2, "role": "钩子", "points": 1, "note": "反常识"},
            {"from": 3, "to": len(subs) - 2, "role": "清单", "points": 3, "note": "三步"},
            {"from": len(subs) - 1, "to": len(subs), "role": "结尾", "points": 0, "note": "关注"}]
    assert b.validate(segs, len(subs)) == []
    assert b.validate([{"from": 1, "to": 2, "role": "钩子"}, {"from": 4, "to": len(subs), "role": "结尾"}], len(subs))   # 漏了第 3 句
    md = b.stats(subs, segs)
    assert "## 3. 分段表" in md and "## 4. 全片指标" in md and "| 1 | 钩子 | [00:00]" in md and "| 无 |" in md
    seg_json, body = b.extract_segments('前言\n```segments\n[{"from":1,"to":2,"role":"钩子","points":1}]\n```\n## 5. 逐段要点\nx')
    assert seg_json[0]["role"] == "钩子" and "```" not in body and body.endswith("x")
    with pytest.raises(b.BreakdownError):
        b.extract_segments("没有代码块")


def test_meeting_templates_from_meetily(env):
    from wb import templates as T
    lst = T.listing()["meetings"]
    assert [m["id"] for m in lst][0] == "meeting.standard_meeting" and len(lst) == 5
    p = T.system_prompt("meeting.standard_meeting", "zh", None)
    assert "## 关键决定" in p and "## 待办事项" in p and "Only use information present in the source text" in p and "[MM:SS]" in p
    assert T.required("meeting.daily_standup", "en") == ["## Date", "## Attendees", "## Yesterday", "## Today", "## Blockers", "## Notes"]
    assert T.valid("meeting.retrospective") and not T.valid("meeting.../x") and not T.valid("meeting.psychatric_session")


def test_generic_check(env, tmp_path):
    from wb import templates as T
    srt = short_srt(tmp_path)
    ok, rep = T.check("# t\n## 摘要\n说了 [00:20]\n## 关键决定\n- x\n## 待办事项\n## 讨论要点\n", srt, "meeting.standard_meeting", "zh")
    assert ok, rep
    ok, rep = T.check("# t\n## 摘要\n说了 [09:20]\n", srt, "meeting.standard_meeting", "zh")
    assert not ok and "缺少小节 ## 关键决定" in rep and "超出视频时长" in rep


def test_pipeline_breakdown_with_fake_model(env, monkeypatch, tmp_path):
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    srt = short_srt(tmp_path)
    from wb import breakdown as b
    n = len(b.sentences(srt))

    def fake_chat(messages, on_progress=None, **k):
        assert "逐句表" in messages[1]["content"] and "钩子 / 承诺" in messages[0]["content"]
        segs = [{"from": 1, "to": 2, "role": "钩子", "points": 1, "note": "反常识"}, {"from": 3, "to": n, "role": "清单", "points": 3, "note": "三步"}]
        return ("```segments\n" + json.dumps(segs, ensure_ascii=False) + "\n```\n\n## 5. 逐段要点\n- 段1 [00:00]\n\n## 6. 可学的写法\n- 反常识开头 [00:00]\n\n"
                "## 7. 收藏点与借鉴边界\n- 三步清单 [00:12]"), {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(srt)
    tid = db.create(kind, src, vid, template="breakdown")
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1, t["log"]
    md = open(p.summary_path(t), encoding="utf-8").read()
    assert md.index("## 1. 开头前 15 秒") < md.index("## 3. 分段表") < md.index("## 5. 逐段要点") and "```segments" not in md


def test_api_rejects_unknown_template(env):
    from fastapi.testclient import TestClient
    with TestClient(env["server"].app) as c:
        assert c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "template": "nope"}).status_code == 400
        r = c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "template": "meeting.project_sync"})
        assert r.status_code == 200 and r.json()["template"] == "meeting.project_sync"
        assert len(c.get("/api/templates").json()["meetings"]) == 5


def test_derive_reuses_transcript(env, monkeypatch):
    """换个用途:沿用原任务的文字稿,换模板出一份新任务,不重新拿稿;原任务保留"""
    from fastapi.testclient import TestClient
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    monkeypatch.setattr(llm, "chat", lambda messages, on_progress=None, **k: (GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}))
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid, template="meeting.project_sync")
    with TestClient(env["server"].app) as c:
        r = c.post(f"/api/tasks/{tid}/derive", json={"template": "course"})
        assert r.status_code == 400 and "文字稿" in r.json()["detail"]          # 还没拿到文字稿
        p.run_task(tid)
        assert c.post(f"/api/tasks/{tid}/derive", json={"template": "nope"}).status_code == 400
        assert c.post("/api/tasks/9999/derive", json={"template": "course"}).status_code == 404
        r = c.post(f"/api/tasks/{tid}/derive", json={"template": "course", "out_lang": "en"})
        assert r.status_code == 200, r.text
        n = r.json()
        assert n["id"] != tid and n["template"] == "course" and n["out_lang"] == "en" and n["meta"]["derived_from"] == tid
        assert "沿用任务" in n["message"] and n["timings"].get("fetch") is not None
    assert os.path.isfile(os.path.join(p.task_root(n["id"]), "课程视频", vid + ".srt"))
    monkeypatch.setattr(env["sources"], "fetch", env["sources"].fetch)
    p.run_task(n["id"])
    t = db.get(n["id"])
    assert t["status"] == "done" and "已有文字稿,跳过拿稿" in t["log"], t["log"]
    assert db.get(tid)["template"] == "meeting.project_sync" and os.path.exists(p.summary_path(db.get(tid)))
