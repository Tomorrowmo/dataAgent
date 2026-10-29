"""LLM client wrapper used for the AI-coding feature and the chat agent.

Two backends behind ONE interface: an OpenAI-compatible path (DeepSeek,
dashscope/qwen, …) driven by raw httpx, and Anthropic's Claude via the official
`anthropic` SDK. Every caller keeps using `chat()` / `stream()` unchanged — the
backend is chosen from the configured model/base_url, so a user switches
providers by editing their BYOK settings and nothing else.

Claude is NOT OpenAI-compatible, and the differences are the kind that fail
loudly at runtime rather than at import:
  • auth is `x-api-key` + `anthropic-version`, not `Authorization: Bearer`
  • the system prompt is a top-level field, not a `role: "system"` message
  • `temperature` is REMOVED on Opus 4.8/4.7 — sending it is a 400, and every
    call site in this repo passes one, so the adapter drops it
  • the response is a list of content blocks, not `choices[0].message.content`
  • images use `{"type": "image", "source": {...}}`, not OpenAI's `image_url`
`_to_anthropic()` below absorbs all of that so the callers stay provider-blind.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from ..core.config import get_settings


class LLMError(RuntimeError):
    pass


# Anthropic's own default. Opus 4.8 is the current top-tier model; adaptive
# thinking is the only supported thinking mode on it (budget_tokens is a 400).
_DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def is_anthropic(self) -> bool:
        """Route to Claude when the model or endpoint says so. Inferred rather
        than stored as a separate provider column — same approach the vision
        model picker already uses, and it needs no DB migration: a user just
        sets model `claude-opus-4-8` in Settings."""
        return (self.model or "").lower().startswith("claude") or \
            "anthropic.com" in (self.base_url or "").lower()

    # ── Anthropic backend ───────────────────────────────────────────────────
    def _anthropic_client(self):
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover - dependency is in requirements
            raise LLMError(
                "Claude 需要 anthropic SDK,但当前环境里没有装。请运行 "
                "`pip install anthropic` 后重试。"
            ) from e
        kwargs: Dict[str, Any] = {"api_key": self.api_key}
        # Only forward a custom base_url (proxy/gateway); the default endpoint
        # is the SDK's own, so don't pass the DeepSeek default through.
        if "anthropic.com" not in (self.base_url or "") and self.base_url:
            if self.model and self.model.lower().startswith("claude") and "deepseek" not in self.base_url:
                kwargs["base_url"] = self.base_url
        return AsyncAnthropic(**kwargs)

    @staticmethod
    def _to_anthropic(messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Split OpenAI-shaped messages into Anthropic's (system, messages).

        Three shape differences are handled here:
          1. `role: "system"` entries become the top-level `system` string
             (several concatenated with blank lines if the caller sent more
             than one).
          2. OpenAI image parts `{"type": "image_url", "image_url": {"url": …}}`
             become `{"type": "image", "source": {…}}`. Only `data:` URLs are
             converted to base64 blocks; an http(s) URL passes through as
             Anthropic's `url` source.
          3. Anthropic rejects two consecutive same-role messages in some
             shapes and requires the first message to be `user`, so a leading
             assistant turn is dropped and adjacent same-role turns are merged.
        """
        import base64 as _b64
        import re as _re

        system_parts: List[str] = []
        out: List[Dict[str, Any]] = []

        def conv_content(content: Any) -> Any:
            if not isinstance(content, list):
                return content
            blocks: List[Dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    blocks.append({"type": "text", "text": str(part)})
                    continue
                if part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    m = _re.match(r"^data:([^;]+);base64,(.*)$", url, flags=_re.DOTALL)
                    if m:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": m.group(1),
                                       "data": m.group(2)},
                        })
                    elif url:
                        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
                elif part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
                else:
                    blocks.append(part)
            return blocks

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    system_parts.append(content)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            block = {"role": role, "content": conv_content(content)}
            # First turn must be `user`; merge adjacent same-role turns.
            if not out and role == "assistant":
                continue
            if out and out[-1]["role"] == role:
                prev, cur = out[-1]["content"], block["content"]
                if isinstance(prev, str) and isinstance(cur, str):
                    out[-1]["content"] = f"{prev}\n\n{cur}"
                else:
                    p = prev if isinstance(prev, list) else [{"type": "text", "text": str(prev)}]
                    c = cur if isinstance(cur, list) else [{"type": "text", "text": str(cur)}]
                    out[-1]["content"] = p + c
                continue
            out.append(block)

        if not out:  # the API requires at least one message
            out = [{"role": "user", "content": "(empty)"}]
        return ("\n\n".join(system_parts) or None), out

    @staticmethod
    def _anthropic_text(message: Any) -> str:
        """Concatenate the text blocks of a Message, skipping thinking blocks
        (which carry empty text under the default `display: "omitted"`)."""
        parts = [b.text for b in getattr(message, "content", []) if getattr(b, "type", "") == "text"]
        return "".join(parts)

    async def _chat_anthropic(
        self, messages: List[Dict[str, Any]], *, max_tokens: int, json_mode: bool,
    ) -> str:
        system, msgs = self._to_anthropic(messages)
        if json_mode:
            # Anthropic's structured outputs need a concrete JSON Schema, and
            # these callers only want "some JSON object" — so ask in the prompt
            # instead of inventing a schema that would reject valid replies.
            hint = "You must reply with a single valid JSON object and nothing else — no prose, no code fences."
            system = f"{system}\n\n{hint}" if system else hint
        client = self._anthropic_client()
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model or _DEFAULT_CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": msgs,
                # NOTE: `temperature` is deliberately NOT forwarded — it is
                # removed on Opus 4.8/4.7 and returns a 400.
            }
            if system:
                kwargs["system"] = system
            resp = await client.messages.create(**kwargs)
        except Exception as e:
            raise LLMError(f"Claude 调用失败: {type(e).__name__}: {str(e)[:400]}") from e
        finally:
            await client.close()
        if getattr(resp, "stop_reason", None) == "refusal":
            raise LLMError("Claude 以安全策略拒绝了这次请求,请换个问法或改用其他模型。")
        return self._anthropic_text(resp)

    async def _stream_anthropic(
        self, messages: List[Dict[str, Any]], *, max_tokens: int,
    ) -> AsyncIterator[str]:
        system, msgs = self._to_anthropic(messages)
        client = self._anthropic_client()
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model or _DEFAULT_CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": msgs,
            }
            if system:
                kwargs["system"] = system
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
        except Exception as e:
            raise LLMError(f"Claude 流式调用失败: {type(e).__name__}: {str(e)[:400]}") from e
        finally:
            await client.close()

    # ── public API (provider-agnostic) ──────────────────────────────────────
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        json_mode: bool = False,
    ) -> str:
        if not self.is_configured:
            raise LLMError(
                "LLM is not configured. Set DEEPSEEK_API_KEY in .env, or store a per-user API key in Settings."
            )
        if self.is_anthropic:
            # `temperature` accepted and ignored — see the module docstring.
            return await self._chat_anthropic(messages, max_tokens=max_tokens, json_mode=json_mode)
        text, finish = await self._chat_once(messages, temperature, max_tokens, json_mode, thinking_off=False)
        if not text and finish == "length" and self._thinking_on():
            # Reasoning ate the whole budget before any answer — retry without it.
            text, finish = await self._chat_once(messages, temperature, max_tokens, json_mode, thinking_off=True)
        if not text:
            raise LLMError(f"模型没有返回任何内容(finish_reason={finish}),请重试。")
        return text

    # ── OpenAI-compatible backend ───────────────────────────────────────────
    @property
    def _is_deepseek(self) -> bool:
        return "deepseek" in (self.base_url or "").lower()

    def _thinking_on(self) -> bool:
        """DeepSeek V4 thinks unless told not to; other providers: assume no."""
        return self._is_deepseek and get_settings().deepseek_thinking.strip().lower() != "disabled"

    def _payload(self, messages, temperature: float, max_tokens: int, *, stream: bool, thinking_off: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": stream,
        }
        if self._is_deepseek:
            mode = "disabled" if thinking_off else get_settings().deepseek_thinking.strip().lower()
            if mode in ("enabled", "disabled"):
                payload["thinking"] = {"type": mode}
            if mode != "disabled":
                # Reasoning tokens count against max_tokens on DeepSeek; give them
                # their own headroom so the answer still gets `max_tokens`.
                payload["max_tokens"] = max_tokens + get_settings().llm_thinking_headroom
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def _chat_once(self, messages, temperature, max_tokens, json_mode, *, thinking_off: bool) -> Tuple[str, Optional[str]]:
        payload = self._payload(messages, temperature, max_tokens, stream=False, thinking_off=thinking_off)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code >= 400:
                raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            try:
                choice = data["choices"][0]
                return choice["message"].get("content") or "", choice.get("finish_reason")
            except (KeyError, IndexError) as e:
                raise LLMError(f"unexpected LLM response shape: {e}") from e

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> AsyncIterator[str]:
        if not self.is_configured:
            raise LLMError("LLM is not configured.")
        if self.is_anthropic:
            async for delta in self._stream_anthropic(messages, max_tokens=max_tokens):
                yield delta
            return
        state: Dict[str, Any] = {}
        got = False
        async for delta in self._stream_once(messages, temperature, max_tokens, state, thinking_off=False):
            got = True
            yield delta
        if not got and state.get("finish") == "length" and self._thinking_on():
            # Nothing was emitted yet, so a clean retry without thinking is safe.
            async for delta in self._stream_once(messages, temperature, max_tokens, state, thinking_off=True):
                got = True
                yield delta
        if not got:
            raise LLMError(f"模型没有返回任何内容(finish_reason={state.get('finish')}),请重试。")

    async def _stream_once(self, messages, temperature, max_tokens, state: Dict[str, Any], *, thinking_off: bool) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens, stream=True, thinking_off=thinking_off)
        state["finish"] = None
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            ) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise LLMError(f"LLM HTTP {r.status_code}: {body[:500].decode('utf-8', errors='ignore')}")
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    try:
                        obj = json.loads(chunk)
                    except Exception:
                        continue
                    for choice in obj.get("choices") or []:
                        state["finish"] = choice.get("finish_reason") or state["finish"]
                        delta = (choice.get("delta") or {}).get("content") or ""
                        if delta:
                            yield delta
