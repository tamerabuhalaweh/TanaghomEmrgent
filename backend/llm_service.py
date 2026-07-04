"""LLM helpers using the optional universal LLM adapter.

Supported providers: openai (gpt-5.2, gpt-5.4), anthropic (claude-sonnet-4-6),
gemini (gemini-3-flash-preview / gemini-3.1-pro-preview).
"""
import os
import json
import uuid
import logging
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
except ImportError:  # pragma: no cover - validated by backend import/startup behavior.
    LlmChat = None
    UserMessage = None

load_dotenv(Path(__file__).parent / ".env")
logger = logging.getLogger(__name__)

UNIVERSAL_LLM_KEY = os.environ.get("UNIVERSAL_LLM_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")

PROVIDER_DEFAULTS = {
    "openai": "gpt-5.2",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3-flash-preview",
}


def _ensure_llm_adapter_available() -> None:
    if not UNIVERSAL_LLM_KEY:
        raise RuntimeError("UNIVERSAL_LLM_KEY is not configured")
    if LlmChat is None or UserMessage is None:
        raise RuntimeError(
            "Optional universal LLM adapter package is not installed. "
            "Install it from the approved source before enabling AI generation."
        )


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


async def generate_post_ideas(
    prompt: str,
    provider: str = "openai",
    model: Optional[str] = None,
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

    _ensure_llm_adapter_available()

    chat = LlmChat(
        **{"api_key": UNIVERSAL_LLM_KEY},
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

    _ensure_llm_adapter_available()

    chat = LlmChat(
        **{"api_key": UNIVERSAL_LLM_KEY},
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
