"""写总结用的模型。三种来源,在「设置」里选(存在配置文件的 provider 字段):

  claude  本机的 Claude Code(`claude -p`),用你已登录的 Claude Pro / Max 订阅,不用 API Key
  codex   本机的 Codex CLI(`codex exec`),用你已登录的 ChatGPT Plus / Pro 账号,不用 API Key
  api     任意 OpenAI 兼容接口(默认 DeepSeek deepseek-chat),要填 API Key
  harness 本机的 DeepSeek Harness 桌面版(`dsh headless`),用你在 Harness 里登录的 DeepSeek 账号,不用 API Key
  auto    默认:填了 Key 用 api;否则依次 claude、codex、harness

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
    "harness": {"name": "DeepSeek Harness(已登录的 DeepSeek 账号)", "cmd": None},
}

# ---------- DeepSeek Harness ----------
# Harness 的无界面模式(dsh headless)默认只认 API Key,还把账号登录用的三个插件关了。
# 这里用一个覆盖配置把它们打开、模型来源改成「已登录的 DeepSeek 账号」,不用 API Key。
# 这是 Harness 文档里没写的用法(2026-11 实测 Harness 0.2 预览版可用),升级后可能失效:失效时报错里说清楚,改用 API Key。
HARNESS_PATCH = """- id: credentials
  name: "@deepseek-ai/dsh-credentials-local"
  disabled: false
- id: authorization
  name: "@deepseek-ai/dsh-authorization"
  disabled: false
- id: deepseek-account
  name: "@deepseek-ai/dsh-deepseek-account"
  disabled: false
  config:
    desktopPlatform: {platform}
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: deepseek-account
    model: {model}
"""
HARNESS_MODEL = "deepseek-flash"          # 写总结:能看图
HARNESS_REVIEW_MODEL = "deepseek-v4-pro"  # 审核 / 复核:推理更强(不看图)


def _dsh_home():
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def find_dsh():
    """Harness 自带的 dsh 命令:桌面版不把它放进 PATH,按安装位置找"""
    cands = [os.environ.get("WORKBENCH_DSH")]
    if os.name == "nt":
        la, pf = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")
        cands += [os.path.join(d, "DeepSeek Harness", "resources", "runtime", "cli", "bin", "dsh.cmd") for d in
                  (os.path.join(la, "Programs"), pf) if d]           # Windows 位置未实测
    else:
        cands += [os.path.join(d, "DeepSeek Harness.app", "Contents", "Resources", "runtime", "cli", "bin", "dsh")
                  for d in ("/Applications", os.path.expanduser("~/Applications"))]
    cands.append(shutil.which("dsh"))
    return next((c for c in cands if c and os.path.isfile(c)), None)


def harness_signed_in():
    """Harness 里登录过 DeepSeek 账号:凭证文件里有账号令牌这一条(只看有没有,不读内容)"""
    p = os.path.join(_dsh_home(), ".credentials.yaml")
    try:
        text = open(p, encoding="utf-8").read()
    except OSError:
        return False
    i = text.find("deepseek-account-platform/default:")
    return i >= 0 and "token:" in text[i:i + 400]


def harness_status():
    dsh = find_dsh()
    if not dsh:
        return False, "没找到 DeepSeek Harness 桌面版"
    if not harness_signed_in():
        return False, "装了 DeepSeek Harness,但还没登录 DeepSeek 账号:打开 Harness 登录一次"
    return True, dsh


class LLMError(Exception):
    pass


def available():
    """各来源能不能用:{provider: (能用, 说明)}"""
    cfg = llm_config()
    out = {}
    for p, info in PROVIDERS.items():
        if p == "harness":
            out[p] = harness_status()
        elif info["cmd"]:
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
    for cand in ("api", "claude", "codex", "harness"):
        if av[cand][0]:
            return cand
    raise LLMError("没有能用的模型:装好并登录 Claude Code 或 Codex,或者装 DeepSeek Harness 并登录 DeepSeek 账号,或者在「设置」里填 API Key(见 README)")


def chat(messages, on_progress=None, max_tokens=8000, temperature=0.3, timeout=1200, provider=None, model=None,
         images_dir=None, images=()):
    """provider 不给就按设置选(见 resolve);审核时传另一家(见 review.reviewer)。model 只对 API 有效(审核用推理模型)。
    看图:Claude Code 给 images_dir(只读,用 Read 工具自己挑着看);Codex 把 images 里的图附在提示后面;API 不看图"""
    p = provider if provider in PROVIDERS else resolve()
    if p == "api":
        return _api(messages, on_progress, max_tokens, temperature, timeout, model)
    if on_progress:
        on_progress(0)
    if p == "claude":
        return _claude(messages, timeout, images_dir)
    if p == "harness":
        return _harness(messages, timeout, model or HARNESS_MODEL)
    return _codex(messages, timeout, images)


def can_see_images(provider):
    return provider in ("claude", "codex", "harness")


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


def _claude(messages, timeout, images_dir=None):
    system, prompt = _flatten(messages)
    with tempfile.TemporaryDirectory(prefix="wb-claude-") as tmp:
        sp = os.path.join(tmp, "system.md")
        open(sp, "w", encoding="utf-8").write(system)
        see = ["--add-dir", images_dir, "--allowedTools", "Read,Glob"] if images_dir and os.path.isdir(images_dir) else []
        out = _run(["claude", "-p", "--output-format", "json", "--no-session-persistence",
                    "--system-prompt-file", sp, *see, "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch"],
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


def _codex(messages, timeout, images=()):
    system, prompt = _flatten(messages)
    imgs = [f"--image={f}" for f in list(images)[:20] if os.path.isfile(f)]       # 附图:最多 20 张(用 = 写法,免得后面的 - 被当成图)
    with tempfile.TemporaryDirectory(prefix="wb-codex-") as tmp:
        last = os.path.join(tmp, "last.md")
        _run(["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--color", "never",
              "-C", tmp, "-o", last, *imgs, "-"],
             f"{system}\n\n---\n\n{prompt}\n\n(直接输出回答全文,不要运行任何命令、不要读写文件。)", timeout, tmp)
        text = open(last, encoding="utf-8").read().strip() if os.path.exists(last) else ""
    if not text:
        raise LLMError("Codex 没有返回内容")
    return text, {"model": "codex", "usage": None, "finish_reason": "stop"}


def _harness(messages, timeout, model):
    """dsh headless:只读权限、在空的临时目录里跑,提示从标准输入进去,只取最后的回答。
    截图目录不用另外授权:只读模式下 Harness 能读本机文件(只是不能改),提示里写了路径它会自己打开"""
    dsh = find_dsh()
    if not dsh:
        raise LLMError("没找到 DeepSeek Harness:到 deepseek.com 下载桌面版装好,或者在「设置」里换一种写总结的方式")
    system, prompt = _flatten(messages)
    with tempfile.TemporaryDirectory(prefix="wb-dsh-") as tmp:
        patch = os.path.join(tmp, "account.yml")
        plat = "win32" if os.name == "nt" else "darwin"
        open(patch, "w", encoding="utf-8").write(HARNESS_PATCH.format(platform=plat, model=model))
        try:
            out = _run([dsh, "headless", "--patch", patch, "--permission-mode", "read-only", "-"],
                       f"{system}\n\n---\n\n{prompt}\n\n(直接输出回答全文,不要修改任何文件。)", timeout, tmp)
        except LLMError as e:
            msg = str(e)
            if "ACCOUNT_SIGN_IN_REQUIRED" in msg:
                raise LLMError("DeepSeek Harness 没登录账号:打开 Harness 用 DeepSeek 账号登录一次,再点「重跑」") from e
            if "did not activate" in msg or "MISSING_CREDENTIAL" in msg:
                raise LLMError("DeepSeek Harness 的账号登录方式用不了了(可能是 Harness 升级后改了):先在「设置」里改用 API Key,"
                               "并把这条报错发给工作台作者: " + msg[-200:]) from e
            raise
    text = out.strip()
    if not text:
        raise LLMError("DeepSeek Harness 没有返回内容")
    return text, {"model": f"harness · {model}", "usage": None, "finish_reason": "stop"}


# ---------- OpenAI 兼容接口 ----------
def _api(messages, on_progress, max_tokens, temperature, timeout, model=None):
    cfg = llm_config()
    model = model or cfg.model
    if not cfg.api_key:
        raise LLMError("没有配置模型 Key:设环境变量 DEEPSEEK_API_KEY,或写 ~/.config/lecture-workbench/config.json(见 README)")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": True}
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    parts, usage, finish = [], None, None
    try:
        with httpx.stream("POST", f"{cfg.base_url}/chat/completions", json=body, headers=headers,
                          timeout=httpx.Timeout(timeout, connect=20)) as r:
            if r.status_code != 200:
                body = r.read().decode("utf-8", "replace")[:300]
                if r.status_code == 402:
                    raise LLMError("API 账户余额不足:到 DeepSeek 开放平台(platform.deepseek.com)充值后,回来点「重跑」")
                if r.status_code in (401, 403):
                    raise LLMError("API Key 不对或已删除:到「设置 → 写总结的 AI」重新粘贴(怎么拿 Key 见首页的图文说明)")
                raise LLMError(f"模型接口返回 {r.status_code}: {body}")
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
    return text, {"model": model, "usage": usage, "finish_reason": finish}
