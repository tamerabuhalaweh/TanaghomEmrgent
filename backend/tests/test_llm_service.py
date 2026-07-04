import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm_service


class _FakeGeminiResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '[{"platform":"instagram","format":"reel","hook":"Hook","caption":"Caption","cta":"Register","hashtags":["#event"],"reasoning":"Relevant"}]'
                            }
                        ]
                    }
                }
            ]
        }


class _FakeGeminiQuotaResponse:
    status_code = 429
    text = '{"error":{"status":"RESOURCE_EXHAUSTED","message":"credits depleted"}}'

    def json(self):
        return {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "credits depleted",
            }
        }


class _FakeGemmaResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '[{"platform":"instagram","format":"reel","hook":"Gemma Hook","caption":"Gemma Caption","cta":"Register","hashtags":["#event"],"reasoning":"Relevant"}]'
                    }
                }
            ]
        }


class _FakeGemmaWrappedResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"ideas":[{"platform":"instagram","type":"reel","title":"Wrapped Hook","body":"Wrapped Caption","call_to_action":"Register","tags":"#event #leadership","why":"Strong fit"}]}'
                    }
                }
            ]
        }


class _FakeGemmaTruncatedResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '[{"platform":"instagram","format":"reel","hook":"First Hook","caption":"First Caption","cta":"Register","hashtags":["#one"],"reasoning":"Good"},{"platform":"meta","format":"text","hook":"Second Hook","caption":"Second Caption","cta":"Register","hashtags":["#two"],"reasoning":"Good"}'
                    }
                }
            ]
        }


class _FakeGemmaNoIdeasResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"message":"I need more context"}'
                    }
                }
            ]
        }


def _patch_gemma_client(monkeypatch, response):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return response

    monkeypatch.setattr(llm_service, "UNIVERSAL_LLM_KEY", "")
    monkeypatch.setattr(llm_service, "GEMMA_API_KEY", "server-gemma-key")
    monkeypatch.setattr(llm_service.httpx, "AsyncClient", FakeAsyncClient)


def test_gemini_generation_uses_tenant_key_without_universal_key(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return _FakeGeminiResponse()

    monkeypatch.setattr(llm_service, "UNIVERSAL_LLM_KEY", "")
    monkeypatch.setattr(llm_service.httpx, "AsyncClient", FakeAsyncClient)

    ideas = asyncio.run(
        llm_service.generate_post_ideas(
            prompt="Sell a live course event",
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="tenant-gemini-key",
            platforms=["instagram"],
        )
    )

    assert ideas[0]["platform"] == "instagram"
    assert calls
    assert calls[0]["headers"]["x-goog-api-key"] == "tenant-gemini-key"
    assert "models/gemini-2.5-flash:generateContent" in calls[0]["url"]


def test_gemma_generation_uses_openai_compatible_endpoint(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return _FakeGemmaResponse()

    monkeypatch.setattr(llm_service, "UNIVERSAL_LLM_KEY", "")
    monkeypatch.setattr(llm_service, "GEMMA_API_KEY", "server-gemma-key")
    monkeypatch.setattr(llm_service, "GEMMA_BASE_URL", "https://api.thesmartlabs.net/gemma4/v1")
    monkeypatch.setattr(llm_service.httpx, "AsyncClient", FakeAsyncClient)

    ideas = asyncio.run(
        llm_service.generate_post_ideas(
            prompt="Sell a live course event",
            provider="gemma",
            model="gemma4-26b-a4b-canary",
            platforms=["instagram"],
        )
    )

    assert ideas[0]["hook"] == "Gemma Hook"
    assert calls
    assert calls[0]["url"] == "https://api.thesmartlabs.net/gemma4/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer server-gemma-key"
    assert calls[0]["json"]["model"] == "gemma4-26b-a4b-canary"


def test_gemma_generation_normalizes_wrapped_ideas(monkeypatch):
    _patch_gemma_client(monkeypatch, _FakeGemmaWrappedResponse())

    ideas = asyncio.run(
        llm_service.generate_post_ideas(
            prompt="Sell a live course event",
            provider="gemma",
            model="gemma4-26b-a4b-canary",
            platforms=["instagram"],
        )
    )

    assert len(ideas) == 1
    assert ideas[0]["hook"] == "Wrapped Hook"
    assert ideas[0]["caption"] == "Wrapped Caption"
    assert ideas[0]["format"] == "reel"
    assert ideas[0]["hashtags"] == ["#event", "#leadership"]


def test_gemma_generation_salvages_truncated_array(monkeypatch):
    _patch_gemma_client(monkeypatch, _FakeGemmaTruncatedResponse())

    ideas = asyncio.run(
        llm_service.generate_post_ideas(
            prompt="Sell a live course event",
            provider="gemma",
            model="gemma4-26b-a4b-canary",
            platforms=["instagram", "meta"],
            n=4,
        )
    )

    assert [idea["hook"] for idea in ideas] == ["First Hook", "Second Hook"]
    assert [idea["platform"] for idea in ideas] == ["instagram", "meta"]


def test_gemma_generation_rejects_response_with_no_usable_ideas(monkeypatch):
    _patch_gemma_client(monkeypatch, _FakeGemmaNoIdeasResponse())

    with pytest.raises(llm_service.LLMProviderError) as exc:
        asyncio.run(
            llm_service.generate_post_ideas(
                prompt="Sell a live course event",
                provider="gemma",
                model="gemma4-26b-a4b-canary",
                platforms=["instagram"],
            )
        )

    assert exc.value.status_code == 502
    assert "no usable post ideas" in str(exc.value)


def test_gemini_quota_error_is_actionable(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return _FakeGeminiQuotaResponse()

    monkeypatch.setattr(llm_service.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(llm_service.LLMProviderError) as exc:
        asyncio.run(
            llm_service.generate_post_ideas(
                prompt="Sell a live course event",
                provider="gemini",
                model="gemini-2.5-flash",
                api_key="tenant-gemini-key",
                platforms=["instagram"],
            )
        )

    assert exc.value.status_code == 402
    assert "billing or quota is exhausted" in str(exc.value)


def test_generation_requires_tenant_or_universal_key(monkeypatch):
    monkeypatch.setattr(llm_service, "UNIVERSAL_LLM_KEY", "")

    with pytest.raises(RuntimeError, match="Tenant LLM key or UNIVERSAL_LLM_KEY"):
        asyncio.run(
            llm_service.generate_post_ideas(
                prompt="Sell a live course event",
                provider="gemini",
                model="gemini-2.5-flash",
            )
        )
