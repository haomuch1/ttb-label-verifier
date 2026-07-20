"""Anthropic backend: one Claude vision call via structured outputs."""

import base64
import os

from anthropic import AsyncAnthropic

from app.extractors.base import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    ExtractionResult,
    prepare_image,
)
from app.models import Extraction

# Default chosen for the hard <5s warm-latency requirement (a prior vendor
# pilot died at 30-40s). claude-haiku-4-5 is the fastest current model and
# supports both vision and structured outputs.
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096


class AnthropicExtractor:
    name = "anthropic"

    def __init__(self) -> None:
        self.model = os.environ.get("EXTRACTION_MODEL", DEFAULT_MODEL)
        self._client: AsyncAnthropic | None = None

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic()
        return self._client

    async def extract(self, images: list[tuple[bytes, str]]) -> ExtractionResult:
        content = []
        for data, media_type in images:
            data, media_type = prepare_image(data, media_type)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode(),
                },
            })
        content.append({"type": "text", "text": USER_PROMPT})

        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=Extraction,
        )
        return ExtractionResult(
            extraction=response.parsed_output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
        )
