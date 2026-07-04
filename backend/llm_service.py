"""LLM helpers using the optional universal LLM adapter.

Supported providers: openai (gpt-5.2, gpt-5.4), anthropic (claude-sonnet-4-6),
gemini (gemini-3-flash-preview / gemini-3.1-pro-preview), gemma
(OpenAI-compatible SmartLabs Gemma endpoint).
"""
import os
import json
import uuid
import logging
import re
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
except ImportError:  # pragma: no cover - validated by backend import/startup behavior.
    LlmChat = None
    UserMessage = None

load_dotenv(Path(__file__).parent / ".env")
logger = logging.getLogger(__name__)

UNIVERSAL_LLM_KEY = os.environ.get("UNIVERSAL_LLM_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
GEMMA_API_KEY = os.environ.get("GEMMA_API_KEY", "")
GEMMA_BASE_URL = os.environ.get("GEMMA_BASE_URL", "https://api.thesmartlabs.net/gemma4/v1").rstrip("/")

PROVIDER_DEFAULTS = {
    "openai": "gpt-5.2",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "gemma": "gemma4-26b-a4b-canary",
}


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _resolve_api_key(api_key: Optional[str] = None) -> str:
    resolved = api_key or UNIVERSAL_LLM_KEY
    if not resolved:
        raise RuntimeError("Tenant LLM key or UNIVERSAL_LLM_KEY is not configured")
    return resolved


def _resolve_gemma_api_key(api_key: Optional[str] = None) -> str:
    resolved = api_key or GEMMA_API_KEY or UNIVERSAL_LLM_KEY
    if not resolved:
        raise RuntimeError("Tenant Gemma key, GEMMA_API_KEY, or UNIVERSAL_LLM_KEY is not configured")
    return resolved


def _ensure_llm_adapter_available(api_key: Optional[str] = None) -> str:
    resolved_key = _resolve_api_key(api_key)
    if LlmChat is None or UserMessage is None:
        raise RuntimeError(
            "Optional universal LLM adapter package is not installed. "
            "Install it from the approved source before enabling AI generation."
        )
    return resolved_key


def _extract_json(text: str):
    """Extract the first JSON object/array from a text blob."""
    # Try direct
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # find outermost braces/brackets
    for open_c, close_c in [("[", "]"), ("{", "}")]:
        i = text.find(open_c)
        j = text.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return None


def _extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    return "\n".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()


async def _send_gemini_message(
    *,
    api_key: str,
    model: str,
    system_message: str,
    user_prompt: str,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system_message}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        message = "Gemini API request failed"
        status_code = 502
        try:
            payload = response.json()
            error = payload.get("error") or {}
            upstream_message = str(error.get("message") or "").strip()
            upstream_status = str(error.get("status") or "").strip()
        except Exception:
            upstream_message = response.text[:300]
            upstream_status = ""

        if response.status_code == 429 or upstream_status == "RESOURCE_EXHAUSTED":
            message = (
                "Gemini billing or quota is exhausted for the configured tenant key. "
                "Add credits or replace the key in AI Settings, then try again."
            )
            status_code = 402
        elif response.status_code in (400, 401, 403):
            message = (
                "Gemini rejected the configured tenant key or model. "
                "Check the provider, API key, model name, and project permissions in AI Settings."
            )
            status_code = 400
        elif upstream_message:
            message = f"Gemini API request failed: {upstream_message[:180]}"
        raise LLMProviderError(message, status_code=status_code)
    text = _extract_gemini_text(response.json())
    if not text:
        raise RuntimeError("Gemini API returned no text content")
    return text


def _extract_chat_completion_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


async def _send_gemma_message(
    *,
    api_key: str,
    model: str,
    system_message: str,
    user_prompt: str,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
        "top_p": 0.9,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{GEMMA_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        message = "Gemma API request failed"
        status_code = 502
        try:
            body = response.json()
            upstream_message = str((body.get("error") or {}).get("message") or body.get("message") or "").strip()
        except Exception:
            upstream_message = response.text[:300]
        if response.status_code in (400, 401, 403):
            message = (
                "Gemma rejected the configured tenant key or model. "
                "Check the provider, API key, model name, and SmartLabs permissions in AI Settings."
            )
            status_code = 400
        elif upstream_message:
            message = f"Gemma API request failed: {upstream_message[:180]}"
        raise LLMProviderError(message, status_code=status_code)
    text = _extract_chat_completion_text(response.json())
    if not text:
        raise RuntimeError("Gemma API returned no text content")
    return text


async def generate_post_ideas(
    prompt: str,
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    platforms: Optional[list] = None,
    audience: Optional[dict] = None,
    goal: str = "max_reach",
    n: int = 4,
    language: str = "en",
) -> list:
    """Generate a list of AI post ideas for the campaign builder."""
    provider = provider if provider in PROVIDER_DEFAULTS else "openai"
    model = model or PROVIDER_DEFAULTS[provider]
    platforms = platforms or ["instagram", "meta", "youtube"]
    audience = audience or {}

    lang_instr = "Respond in Arabic." if language == "ar" else "Respond in English."
    system_message = (
        "You are an elite social-media strategist and copywriter specializing in "
        "event marketing, FOMO campaigns, and multi-platform content. "
        "You output strict JSON only, no prose outside the JSON."
        f" {lang_instr}"
    )

    schema = (
        '[{"platform": "instagram|meta|youtube|tiktok|whatsapp|email", '
        '"format": "video|carousel|text|image|reel|email", '
        '"hook": "one-line attention hook", '
        '"caption": "post caption / body", '
        '"cta": "call to action", '
        '"hashtags": ["#tag"], '
        '"reasoning": "why this works for the algorithm & audience"}]'
    )

    user_prompt = f"""Task: Generate {n} distinct social media post ideas.

CAMPAIGN BRIEF:
{prompt}

TARGET AUDIENCE:
- Age range: {audience.get('age_range', 'not specified')}
- Gender: {audience.get('gender', 'all')}
- Location: {audience.get('geo', 'not specified')}
- Segment: {audience.get('segment', 'warm + cold leads')}

TARGET PLATFORMS: {', '.join(platforms)}
OPTIMIZATION GOAL: {goal.replace('_', ' ')}

Return ONLY a JSON array following this exact schema:
{schema}

Ensure each idea targets a specific platform from the list. Vary formats.
Make hooks pattern-interrupting. CTAs must drive to registration/purchase.
"""

    if provider == "gemini":
        resolved_key = _resolve_api_key(api_key)
        resp = await _send_gemini_message(
            api_key=resolved_key,
            model=model,
            system_message=system_message,
            user_prompt=user_prompt,
        )
        parsed = _extract_json(resp) or []
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed

    if provider == "gemma":
        resp = await _send_gemma_message(
            api_key=_resolve_gemma_api_key(api_key),
            model=model,
            system_message=system_message,
            user_prompt=user_prompt,
        )
        parsed = _extract_json(resp) or []
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed

    resolved_key = _resolve_api_key(api_key)
    _ensure_llm_adapter_available(resolved_key)

    chat = LlmChat(
        **{"api_key": resolved_key},
        session_id=f"post-gen-{uuid.uuid4()}",
        system_message=system_message,
    ).with_model(provider, model)

    resp = await chat.send_message(UserMessage(text=user_prompt))
    parsed = _extract_json(resp) or []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


async def suggest_campaign_strategy(
    prompt: str,
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    language: str = "en",
) -> dict:
    """Generate a campaign strategy blueprint (topics, funnel steps)."""
    provider = provider if provider in PROVIDER_DEFAULTS else "openai"
    model = model or PROVIDER_DEFAULTS[provider]

    lang_instr = "Respond in Arabic." if language == "ar" else "Respond in English."
    schema = (
        '{"topics": ["topic 1", "topic 2"], '
        '"funnel_stages": [{"name": "Awareness", "channels": ["meta","yt"], "content_types": ["reel","carousel"]}], '
        '"key_messages": ["msg1"], '
        '"fomo_triggers": ["trigger1"]}'
    )

    if provider == "gemini":
        resolved_key = _resolve_api_key(api_key)
        resp = await _send_gemini_message(
            api_key=resolved_key,
            model=model,
            system_message=f"You are an elite campaign strategist. Output strict JSON only. {lang_instr}",
            user_prompt=f"Build a marketing strategy for this brief. Return JSON schema:\n{schema}\n\nBrief:\n{prompt}",
        )
        return _extract_json(resp) or {}

    if provider == "gemma":
        resp = await _send_gemma_message(
            api_key=_resolve_gemma_api_key(api_key),
            model=model,
            system_message=f"You are an elite campaign strategist. Output strict JSON only. {lang_instr}",
            user_prompt=f"Build a marketing strategy for this brief. Return JSON schema:\n{schema}\n\nBrief:\n{prompt}",
        )
        return _extract_json(resp) or {}

    resolved_key = _resolve_api_key(api_key)
    _ensure_llm_adapter_available(resolved_key)

    chat = LlmChat(
        **{"api_key": resolved_key},
        session_id=f"strategy-{uuid.uuid4()}",
        system_message=f"You are an elite campaign strategist. Output strict JSON only. {lang_instr}",
    ).with_model(provider, model)

    resp = await chat.send_message(
        UserMessage(
            text=f"Build a marketing strategy for this brief. Return JSON schema:\n{schema}\n\nBrief:\n{prompt}"
        )
    )
    parsed = _extract_json(resp) or {}
    return parsed
