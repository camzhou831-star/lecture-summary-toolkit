"""OpenAI 兼容的对话接口(默认 DeepSeek deepseek-chat)。流式读回,边写边报进度。"""
import json

import httpx

from .config import llm_config


class LLMError(Exception):
    pass


def chat(messages, on_progress=None, max_tokens=8000, temperature=0.3, timeout=900):
    cfg = llm_config()
    if not cfg.api_key:
        raise LLMError("没有配置模型 Key:设环境变量 DEEPSEEK_API_KEY,或写 ~/.config/lecture-workbench/config.json(见 workbench/README.md)")
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
