"""
Tests for LLMAnalyzer fallback logic.
All HTTP / SDK calls are mocked — no real network calls.
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analysis.llm import LLMAnalyzer, LLMResult
from analysis.ollama_client import OllamaUnavailableError, OllamaModelError
from analysis.anthropic_client import AnthropicUnavailableError


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _listings():
    return [
        {
            "year": 2023, "make": "Toyota", "model": "RAV4", "trim": "XLE",
            "price": 30000.0, "mileage": 35000, "monthly_estimated": 535.0,
            "shipping": None, "is_hybrid": False, "value_score": 65.0,
        }
    ]


def _analyzer():
    """Return an LLMAnalyzer with both backends pre-configured."""
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.ollama    = MagicMock()
    analyzer.anthropic = MagicMock()
    analyzer.backend_used = None
    return analyzer


# ── Anthropic available → uses Anthropic (primary) ───────────────────────────

def test_uses_ollama_when_available(monkeypatch):
    """Anthropic is primary; when configured it should be used even if Ollama is available."""
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.return_value = "Great deal on the RAV4."
    analyzer.ollama.is_available.return_value = True

    result = analyzer.analyze(_listings())

    assert result.backend_used == "anthropic_api"
    assert result.analysis     == "Great deal on the RAV4."
    assert result.error        is None
    analyzer.ollama.analyze.assert_not_called()


# ── Ollama fails → falls back to Anthropic ────────────────────────────────────

def test_ollama_unavailable_error_falls_back(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = True
    analyzer.ollama.analyze.side_effect = OllamaUnavailableError("connection refused")
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.return_value = "API analysis here."

    result = analyzer.analyze(_listings())

    assert result.backend_used == "anthropic_api"
    assert result.analysis     == "API analysis here."
    assert result.error        is None


def test_ollama_model_error_falls_back(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = True
    analyzer.ollama.analyze.side_effect = OllamaModelError("model not found")
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.return_value = "API analysis here."

    result = analyzer.analyze(_listings())

    assert result.backend_used == "anthropic_api"


def test_ollama_not_available_falls_back(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = False
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.return_value = "API analysis here."

    result = analyzer.analyze(_listings())

    assert result.backend_used == "anthropic_api"
    analyzer.ollama.analyze.assert_not_called()


# ── Both fail → returns none result ──────────────────────────────────────────

def test_both_fail_returns_none_result(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = True
    analyzer.ollama.analyze.side_effect = OllamaUnavailableError("timeout")
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.side_effect = AnthropicUnavailableError("rate limit")

    result = analyzer.analyze(_listings())

    assert result.backend_used == "none"
    assert result.analysis     is None
    assert result.error        is not None


def test_ollama_disabled_anthropic_not_configured_returns_none(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    False)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.anthropic.is_configured.return_value = False

    result = analyzer.analyze(_listings())

    assert result.backend_used == "none"
    assert result.analysis     is None


def test_both_disabled_returns_none(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    False)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", False)

    analyzer = _analyzer()

    result = analyzer.analyze(_listings())

    assert result.backend_used == "none"
    assert result.analysis     is None


# ── Anthropic API not configured → uses none, skips API ──────────────────────

def test_anthropic_not_configured_skips_api(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = False
    analyzer.anthropic.is_configured.return_value = False

    result = analyzer.analyze(_listings())

    assert result.backend_used == "none"
    analyzer.anthropic.analyze.assert_not_called()


# ── LLMResult shape ───────────────────────────────────────────────────────────

def test_result_is_llmresult_instance(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",    True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED", True)

    analyzer = _analyzer()
    analyzer.ollama.is_available.return_value = True
    analyzer.ollama.analyze.return_value = "some analysis"

    result = analyzer.analyze(_listings())

    assert isinstance(result, LLMResult)
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0


def test_result_has_model_used(monkeypatch):
    monkeypatch.setattr("config.OLLAMA_ENABLED",     True)
    monkeypatch.setattr("config.ANTHROPIC_ENABLED",  True)
    monkeypatch.setattr("config.ANTHROPIC_MODEL",    "claude-haiku-4-5-20251001")

    analyzer = _analyzer()
    analyzer.anthropic.is_configured.return_value = True
    analyzer.anthropic.analyze.return_value = "analysis"

    result = analyzer.analyze(_listings())

    assert result.model_used == "claude-haiku-4-5-20251001"


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_contains_listing_data():
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.ollama    = MagicMock()
    analyzer.anthropic = MagicMock()
    analyzer.backend_used = None

    prompt = analyzer.build_prompt(_listings())

    assert "RAV4"       in prompt
    assert "30,000"     in prompt  # price formatted
    assert "XLE"        in prompt
    assert "ANALYSIS REQUEST" in prompt


def test_build_prompt_caps_at_30_listings():
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.ollama    = MagicMock()
    analyzer.anthropic = MagicMock()
    analyzer.backend_used = None

    # Create 40 listings
    many = [
        {
            "year": 2023, "make": "Toyota", "model": "RAV4", "trim": f"Trim{i}",
            "price": 30000.0 + i * 100, "mileage": 30000, "monthly_estimated": 535.0,
            "shipping": None, "is_hybrid": False, "value_score": float(60 - i),
        }
        for i in range(40)
    ]
    prompt = analyzer.build_prompt(many)
    # The table should not exceed 30 data rows
    table_rows = [line for line in prompt.splitlines() if line.startswith("| 2023")]
    assert len(table_rows) <= 30


def test_build_prompt_marks_hybrid():
    analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
    analyzer.ollama    = MagicMock()
    analyzer.anthropic = MagicMock()
    analyzer.backend_used = None

    hybrid_listing = {
        "year": 2023, "make": "Toyota", "model": "RAV4", "trim": "XSE Hybrid",
        "price": 35000.0, "mileage": 20000, "monthly_estimated": 640.0,
        "shipping": None, "is_hybrid": True, "value_score": 75.0,
    }
    prompt = analyzer.build_prompt([hybrid_listing])
    assert "[HYBRID]" in prompt
