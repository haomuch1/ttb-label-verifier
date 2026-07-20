"""Extractor selection. Set EXTRACTOR=anthropic|ollama|mock (default: ollama)."""

import os

from dotenv import load_dotenv

from app.extractors.base import ExtractionResult, Extractor

load_dotenv()

_instances: dict[str, Extractor] = {}


def get_extractor(name: str | None = None) -> Extractor:
    name = (name or os.environ.get("EXTRACTOR", "ollama")).lower()
    if name not in _instances:
        if name == "anthropic":
            from app.extractors.anthropic_extractor import AnthropicExtractor
            _instances[name] = AnthropicExtractor()
        elif name == "ollama":
            from app.extractors.ollama_extractor import OllamaExtractor
            _instances[name] = OllamaExtractor()
        elif name == "mock":
            from app.extractors.mock_extractor import MockExtractor
            _instances[name] = MockExtractor()
        else:
            raise ValueError(f"Unknown extractor '{name}' (anthropic|ollama|mock)")
    return _instances[name]


__all__ = ["Extractor", "ExtractionResult", "get_extractor"]
