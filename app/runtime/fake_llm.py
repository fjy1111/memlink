"""Backward-compatible import for the unified fake LLM adapter."""

from app.llm.clients import FakeLLMClient

FakeLLM = FakeLLMClient

__all__ = ["FakeLLM", "FakeLLMClient"]
