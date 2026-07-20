"""Ollama backend: self-hosted local inference, no key, no network egress.

This is the answer to two constraints at once: the Treasury network blocks
most outbound ML endpoints (so a cloud API is a non-starter in
production), and per-application API cost at ~150K applications/year.
Ollama runs entirely on localhost; the app talks to it over
http://localhost:11434 and nothing leaves the machine.

Uses Ollama's structured outputs (`format` = JSON schema) so the model is
constrained to the same Extraction schema as every other backend.
"""

import base64
import os

import httpx

from app.extractors.base import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    ExtractionResult,
    prepare_image,
)
from app.models import Extraction

DEFAULT_MODEL = "qwen3-vl:8b"
DEFAULT_URL = "http://localhost:11434"
# Local inference is slower than a hosted API; give it room. The <5s
# product target assumes production-grade GPU serving - measured local
# numbers are reported in APPROACH.md.
TIMEOUT_SECONDS = 600


class OllamaExtractor:
    name = "ollama"

    def __init__(self) -> None:
        self.model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        self.base_url = os.environ.get("OLLAMA_URL", DEFAULT_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        return self._client

    async def extract(self, images: list[tuple[bytes, str]]) -> ExtractionResult:
        b64_images = []
        for data, media_type in images:
            data, _ = prepare_image(data, media_type)
            b64_images.append(base64.standard_b64encode(data).decode())

        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": Extraction.model_json_schema(),
                "options": {"temperature": 0, "num_predict": 4096},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT, "images": b64_images},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        extraction = Extraction.model_validate_json(body["message"]["content"])
        return ExtractionResult(
            extraction=extraction,
            input_tokens=body.get("prompt_eval_count", 0),
            output_tokens=body.get("eval_count", 0),
            model=self.model,
        )
