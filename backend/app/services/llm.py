"""DeepSeek (OpenAI-compatible) client wrapper used for the AI-coding feature
and the chat agent. Falls back to a per-user BYOK key when present."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from ..core.config import get_settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

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
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code >= 400:
                raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            try:
                return data["choices"][0]["message"]["content"]
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
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                url,
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
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue
