"""Minimal Ollama client for constrained JSON responses.

A single POST to a documented JSON endpoint. LangChain would wrap this in an
abstraction layer, a dependency and a version-compatibility surface to save
about fifteen lines, which is not a trade worth making.

Two options carry the reliability of this module. `format: "json"` constrains
generation so that unparseable output is impossible rather than merely unlikely
-- no markdown fences, no prose preamble. `temperature: 0` makes decisions
reproducible, without which a demo behaves differently every run.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when the model is unreachable, too slow, or unusable."""


@dataclass(frozen=True, slots=True)
class OllamaSettings:
    base_url: str = "http://localhost:11434"
    model: str = "llama3"
    temperature: float = 0.0

    # A supervisory decision is due every simulated hour. Waiting longer than
    # this is worse than falling back to the deterministic policy.
    timeout_seconds: float = 25.0

    # The response is a two-field JSON object; anything longer is the model
    # rambling, and cutting it off early bounds worst-case latency.
    max_tokens: int = 220


@dataclass(frozen=True, slots=True)
class LlmResponse:
    payload: dict
    latency_seconds: float


class OllamaClient:
    """Talks to a local Ollama server. One request, one JSON object back."""

    def __init__(self, settings: OllamaSettings | None = None) -> None:
        self._settings = settings or OllamaSettings()

    @property
    def model(self) -> str:
        return self._settings.model

    def available_models(self) -> list[str]:
        """Model names the server currently has pulled."""
        try:
            response = httpx.get(f"{self._settings.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama is not reachable at {self._settings.base_url}") from exc

        return [model.get("name", "") for model in response.json().get("models", [])]

    def check_ready(self) -> None:
        """Fail loudly at startup rather than on the first decision of a demo."""
        models = self.available_models()
        if not models:
            raise OllamaError(
                f"Ollama has no models installed. Run: ollama pull {self._settings.model}"
            )
        # Ollama reports tags as "llama3:latest"; accept an untagged request.
        if not any(name.split(":")[0] == self._settings.model.split(":")[0] for name in models):
            raise OllamaError(
                f"Model '{self._settings.model}' not installed. Available: {', '.join(models)}"
            )

    def chat_json(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        """Send one exchange and return the parsed JSON object."""
        request = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._settings.temperature,
                "num_predict": self._settings.max_tokens,
            },
        }

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self._settings.base_url}/api/chat",
                json=request,
                timeout=self._settings.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"{self._settings.model} did not answer within "
                f"{self._settings.timeout_seconds:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        latency = time.perf_counter() - started
        content = response.json().get("message", {}).get("content", "")

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Model returned unparseable JSON: {content[:200]!r}") from exc

        if not isinstance(payload, dict):
            raise OllamaError(f"Expected a JSON object, got {type(payload).__name__}")

        return LlmResponse(payload=payload, latency_seconds=latency)
