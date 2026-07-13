"""tests/test_provider_transport.py - Tests for core/provider_transport.py.

Covers:
  - provider_headers: format-specific headers for OpenAI and Anthropic
  - validate_provider_definition: name, URL, format, key env validation
  - Integration: fetch_models uses correct headers per format
"""

from __future__ import annotations

import pytest

from core.provider_transport import (
    provider_headers,
    validate_provider_definition,
)

# ---------------------------------------------------------------------------
# provider_headers
# ---------------------------------------------------------------------------


class TestProviderHeaders:
    """Unit tests for format-specific HTTP headers."""

    def test_openai_format_uses_bearer_token(self) -> None:
        headers = provider_headers("openai", "sk-test-key")
        assert headers["Authorization"] == "Bearer sk-test-key"
        assert "x-api-key" not in headers

    def test_anthropic_format_uses_x_api_key(self) -> None:
        headers = provider_headers("anthropic", "sk-ant-test-key")
        assert headers["x-api-key"] == "sk-ant-test-key"
        assert "Authorization" not in headers
        assert headers["anthropic-version"] == "2023-06-01"

    def test_unknown_format_defaults_to_openai(self) -> None:
        headers = provider_headers("unknown", "key")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer key"

    def test_all_formats_include_content_type(self) -> None:
        for fmt in ("openai", "anthropic", "unknown"):
            headers = provider_headers(fmt, "key")
            assert headers.get("content-type") == "application/json"


# ---------------------------------------------------------------------------
# validate_provider_definition
# ---------------------------------------------------------------------------


class TestValidateProviderDefinition:
    """Unit tests for provider definition validation."""

    def test_valid_openai_provider(self) -> None:
        defn = validate_provider_definition(
            "myrelay",
            {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "MYRELAY_API_KEY",
                "api_format": "openai",
            },
        )
        assert defn.name == "myrelay"
        assert defn.base_url == "https://api.example.com/v1"
        assert defn.api_key_env == "MYRELAY_API_KEY"
        assert defn.api_format == "openai"

    def test_valid_anthropic_provider(self) -> None:
        defn = validate_provider_definition(
            "claude",
            {
                "base_url": "https://api.anthropic.com",
                "api_key_env": "ANTHROPIC_KEY",
                "api_format": "anthropic",
            },
        )
        assert defn.api_format == "anthropic"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            validate_provider_definition(
                "", {"base_url": "https://x.com", "api_key_env": "K"}
            )

    def test_whitespace_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            validate_provider_definition(
                "   ", {"base_url": "https://x.com", "api_key_env": "K"}
            )

    def test_missing_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires a base_url"):
            validate_provider_definition("test", {"api_key_env": "K"})

    def test_empty_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires a base_url"):
            validate_provider_definition("test", {"base_url": "", "api_key_env": "K"})

    def test_missing_api_key_env_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires an api_key_env"):
            validate_provider_definition("test", {"base_url": "https://x.com"})

    def test_unknown_format_defaults_to_openai(self) -> None:
        defn = validate_provider_definition(
            "test",
            {
                "base_url": "https://x.com",
                "api_key_env": "K",
                "api_format": "graphql",
            },
        )
        assert defn.api_format == "openai"

    def test_definition_is_frozen(self) -> None:
        defn = validate_provider_definition(
            "test",
            {
                "base_url": "https://x.com",
                "api_key_env": "K",
            },
        )
        with pytest.raises(AttributeError):
            defn.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: fetch_models uses format-specific headers
# ---------------------------------------------------------------------------


class TestFetchModelsUsesCorrectHeaders:
    """Integration tests verifying fetch_models uses provider_headers."""

    def test_fetch_models_passes_format_to_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify fetch_models calls provider_headers with the correct format."""
        from core import provider_runtime

        captured_headers: dict = {}

        class FakeClient:
            async def get(self, url, headers=None):
                captured_headers.update(headers or {})

                class Resp:
                    status_code = 200
                    text = ""

                    def raise_for_status(self_):
                        return None

                    def json(self_):
                        return {"data": []}

                return Resp()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        # Patch httpx.AsyncClient to return our fake.
        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

        # Call fetch_models with anthropic format.
        asyncio.run(
            provider_runtime.fetch_models(
                "https://api.anthropic.com", "sk-ant-key", "anthropic"
            )
        )

        assert captured_headers.get("x-api-key") == "sk-ant-key"
        assert "Authorization" not in captured_headers


import asyncio
