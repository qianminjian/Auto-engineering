"""Tests for provider factory multi-provider dispatch (T59)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from auto_engineering.providers.factory import create_provider


class TestFactoryMultiProvider:
    """Provider factory dispatch tests for all 5 backends."""

    def test_create_ollama(self) -> None:
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("ollama")
            from auto_engineering.providers.ollama import OllamaProvider
            assert isinstance(p, OllamaProvider)

    def test_create_glm(self) -> None:
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("glm")
            from auto_engineering.providers.glm import GLMProvider
            assert isinstance(p, GLMProvider)

    def test_create_qwen(self) -> None:
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("qwen")
            from auto_engineering.providers.qwen import QwenProvider
            assert isinstance(p, QwenProvider)

    def test_create_ollama_satisfies_protocol(self) -> None:
        """All providers implement the required methods (structural Protocol check)."""
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("ollama")
        assert hasattr(p, "create_message")
        assert hasattr(p, "close")

    def test_create_glm_satisfies_protocol(self) -> None:
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("glm")
        assert hasattr(p, "create_message")
        assert hasattr(p, "close")

    def test_create_qwen_satisfies_protocol(self) -> None:
        with patch("openai.AsyncOpenAI", autospec=True):
            p = create_provider("qwen")
        assert hasattr(p, "create_message")
        assert hasattr(p, "close")

    def test_create_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("unknown_provider")

    def test_auto_detect_ollama_host(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://gpu:11434"}, clear=True):
            with patch("openai.AsyncOpenAI", autospec=True):
                p = create_provider()
                from auto_engineering.providers.ollama import OllamaProvider
                assert isinstance(p, OllamaProvider)
