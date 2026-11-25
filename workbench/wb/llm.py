"""写总结用的模型。三种来源,在「设置」里选(存在配置文件的 provider 字段):

  claude  本机的 Claude Code(`claude -p`),用你已登录的 Claude Pro / Max 订阅,不用 API Key
  codex   本机的 Codex CLI(`codex exec`),用你已登录的 ChatGPT Plus / Pro 账号,不用 API Key
  api     任意 OpenAI 兼容接口(默认 DeepSeek deepseek-chat),要填 API Key
  auto    默认:填了 Key 用 api;否则有 claude 用 claude;再否则有 codex 用 codex

命令行两种都在一个空的临时目录里跑,只读、不让它动文件;讲义稿从标准输入传进去。
"""
import json
import os
import shutil
import subprocess
import tempfile

import httpx

from .config import llm_config

PROVIDERS = {
    "claude": {"name": "Claude Code(Claude Pro / Max 订阅)", "cmd": "claude"},
    "codex": {"name": "Codex(ChatGPT Plus / Pro 账号)", "cmd": "codex"},
    "api": {"name": "API Key(DeepSeek 或任意 OpenAI 兼容接口)", "cmd": None},
}


class LLMError(Exception):
    pass


def available():
    """各来源能不能用:{provider: (能用, 说明)}"""
    cfg = llm_config()
    out = {}
    for p, info in PROVIDERS.items():
        if info["cmd"]:
            path = shutil.which(info["cmd"])
            out[p] = (bool(path), path or f"没找到 {info['cmd']} 命令")
        else:
            out[p] = (bool(cfg.api_key), cfg.source if cfg.api_key else "没填 API Key")
    return out


def resolve(provider=None):
    """auto → 实际用哪个"""
    p = provider or llm_config().provider
    if p in PROVIDERS:
        return p
    av = available()
    for cand in ("api", "claude", "codex"):
        if av[cand][0]:
            return cand
    raise LLMError("没有能用的模型:装好并登录 Claude Code 或 Codex,或者在「设置」里填 API Key(见 README)")


def chat(messages, on_progress=None, max_tokens=8000, temperature=0.3, timeout=1200):
    p = resolve()
    if p == "api":
        return _api(messages, on_progress, max_tokens, temperature, timeout)
    if on_progress:
        on_progress(0)
    return (_claude if p == "claude" else _codex)(messages, timeout)


# ---------- 本机命令行 ----------
def _flatten(messages):
    """系统提示单独给;其余对话拼成一段(改一轮时要带上上一版总结和检查结果)"""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    if len(rest) == 1:
        return system, rest[0]["content"]
    label = {"user": "## 用户", "assistant": "## 你上一次的回答"}
    return system, "\n\n".join(f"{label[m['role']]}\n\n{m['content']}" for m in rest)


def _run(cmd, stdin_text, timeout, cwd):
    exe = shutil.which(cmd[0])      # Windows 上 npm 装的是 claude.cmd / codex.cmd,直接用名字 subprocess 找不到
    if exe:
        cmd = [exe, *cmd[1:]]
    try:
        r = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd, env=dict(os.environ, NO_COLOR="1"))
    except FileNotFoundError as e:
        raise LLMError(f"找不到命令 {os.path.basename(cmd[0])}") from e
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"{os.path.splitext(os.path.basename(cmd[0]))[0]} 超过 {timeout // 60} 分钟没写完") from e
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip()[-400:]
        name = os.path.splitext(os.path.basename(cmd[0]))[0]
        hint = "(没登录的话先在终端运行一次 " + name + " 登录)" if any(w in tail.lower() for w in ("login", "auth", "log in", "credential")) else ""
        raise LLMError(f"{name} 出错{hint}: {tail}")
    return r.stdout


def _claude(messages, timeout):
    system, prompt = _flatten(messages)
    with tempfile.TemporaryDirectory(prefix="wb-claude-") as tmp:
        sp = os.path.join(tmp, "system.md")
        open(sp, "w", encoding="utf-8").write(system)
        out = _run(["claude", "-p", "--output-format", "json", "--no-session-persistence",
                    "--system-prompt-file", sp, "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch"],
                   prompt, timeout, tmp)
    try:
        j = json.loads(out)
    except ValueError:
        return out.strip(), {"model": "claude-code", "usage": None, "finish_reason": None}
    if j.get("is_error"):
        raise LLMError(f"Claude Code 出错: {str(j.get('result'))[:300]}")
    text = (j.get("result") or "").strip()
    if not text:
        raise LLMError("Claude Code 没有返回内容")
    usage = j.get("usage") or {}
    return text, {"model": "claude-code", "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens") if k in usage},
                  "finish_reason": j.get("subtype")}


def _codex(messages, timeout):
    system, prompt = _flatten(messages)
    with tempfile.TemporaryDirectory(prefix="wb-codex-") as tmp:
        last = os.path.join(tmp, "last.md")
        _run(["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--color", "never",
              "-C", tmp, "-o", last, "-"],
             f"{system}\n\n---\n\n{prompt}\n\n(直接输出总结的 Markdown 全文,不要运行任何命令、不要读写文件。)", timeout, tmp)
        text = open(last, encoding="utf-8").read().strip() if os.path.exists(last) else ""
    if not text:
        raise LLMError("Codex 没有返回内容")
    return text, {"model": "codex", "usage": None, "finish_reason": "stop"}


# ---------- OpenAI 兼容接口 ----------
def _api(messages, on_progress, max_tokens, temperature, timeout):
    cfg = llm_config()
    if not cfg.api_key:
        raise LLMError("没有配置模型 Key:设环境变量 DEEPSEEK_API_KEY,或写 ~/.config/lecture-workbench/config.json(见 README)")
    body = {"model": cfg.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": True}
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    parts, usage, finish = [], None, None
    try:
        with httpx.stream("POST", f"{cfg.base_url}/chat/completions", json=body, headers=headers,
                          timeout=httpx.Timeout(timeout, connect=20)) as r:
            if r.status_code != 200:
                raise LLMError(f"模型接口返回 {r.status_code}: {r.read().decode('utf-8', 'replace')[:300]}")
            n = 0
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                j = json.loads(data)
                if j.get("usage"):
                    usage = j["usage"]
                for ch in j.get("choices", []):
                    piece = (ch.get("delta") or {}).get("content") or ""
                    parts.append(piece)
                    finish = ch.get("finish_reason") or finish
                    n += len(piece)
                if on_progress and n:
                    on_progress(n)
    except httpx.HTTPError as e:
        raise LLMError(f"连不上模型接口 {cfg.base_url}: {e}") from e
    text = "".join(parts).strip()
    if not text:
        raise LLMError("模型没有返回内容")
    return text, {"model": cfg.model, "usage": usage, "finish_reason": finish}
