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
import io
import os

import httpx
from PIL import Image

from app.extractors.base import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    ExtractionResult,
    prepare_image,
)
from app.models import Extraction

def _ollama_schema() -> dict:
    """Rewrite the pydantic schema into what Ollama's grammar engine accepts.

    Ollama 0.32's JSON-schema-to-grammar conversion silently produces empty
    output when the schema uses anyOf (which pydantic emits for every
    Optional field) — confirmed empirically against qwen3-vl. Native
    nullable type unions ("type": ["string", "null"]) work, so: inline all
    $defs, rewrite `anyOf [X, null]` as X with null added to its type (or
    its enum), and mark every property required so the model must state
    null explicitly rather than omit fields.
    """
    schema = Extraction.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = defs[node["$ref"].split("/")[-1]]
            merged = {**ref, **{k: v for k, v in node.items() if k != "$ref"}}
            return resolve(merged)
        if "anyOf" in node:
            options = [resolve(option) for option in node["anyOf"]]
            non_null = [o for o in options if o.get("type") != "null"]
            if len(options) == 2 and len(non_null) == 1:
                base = dict(non_null[0])
                if "description" in node:
                    base.setdefault("description", node["description"])
                if "enum" in base:
                    if None not in base["enum"]:
                        base["enum"] = base["enum"] + [None]
                    base.pop("type", None)
                elif isinstance(base.get("type"), str):
                    base["type"] = [base["type"], "null"]
                return base
            return {**{k: resolve(v) for k, v in node.items() if k != "anyOf"},
                    "anyOf": options}
        resolved = {k: resolve(v) for k, v in node.items() if k != "default"}
        if resolved.get("type") == "object" and "properties" in resolved:
            resolved["required"] = list(resolved["properties"])
        return resolved

    return resolve(schema)


DEFAULT_MODEL = "qwen2.5vl:7b"
DEFAULT_URL = "http://localhost:11434"

# Appended for local models only. Thinking-family models (qwen3-vl) can
# ruminate for thousands of tokens on this task — and Ollama 0.32's
# "think": false silently produces empty content for them — so the prompt
# itself has to curb deliberation. Harmless for non-thinking models.
LOCAL_SUFFIX = (
    "\nDo not deliberate. Any internal reasoning must be at most one short "
    "sentence; then output the JSON immediately."
)
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

    @staticmethod
    def _upscale_small(data: bytes) -> bytes:
        """Upscale low-resolution pages 2x for the local vision encoder.

        Registry printouts arrive as ~600px-wide page images; at that size
        small label text starves a 7B vision encoder. Lanczos 2x measurably
        improves label transcription at the cost of more image tokens.
        """
        img = Image.open(io.BytesIO(data))
        if max(img.size) >= 1400:
            return data
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    async def extract(self, images: list[tuple[bytes, str]]) -> ExtractionResult:
        b64_images = []
        for data, media_type in images:
            data, _ = prepare_image(data, media_type)
            data = self._upscale_small(data)
            b64_images.append(base64.standard_b64encode(data).decode())

        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                # Do NOT pass "think": false here — on Ollama 0.32 with
                # thinking models it silently yields empty content.
                "format": _ollama_schema(),
                # num_ctx: Ollama's default 4096 context silently truncates
                # (done_reason "length") once image tokens + prompt +
                # output add up; 16384 gives comfortable headroom.
                # repeat_penalty guards against the degenerate repetition
                # loops small models fall into on dense form text.
                "options": {"temperature": 0, "num_predict": 8192,
                            "num_ctx": 16384, "repeat_penalty": 1.05},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT + LOCAL_SUFFIX},
                    {"role": "user", "content": USER_PROMPT, "images": b64_images},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        extraction = Extraction.model_validate_json(body["message"]["content"].strip())
        return ExtractionResult(
            extraction=extraction,
            input_tokens=body.get("prompt_eval_count", 0),
            output_tokens=body.get("eval_count", 0),
            model=self.model,
        )
