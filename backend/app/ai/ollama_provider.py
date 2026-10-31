import json
import logging
import time

import httpx

from app.ai.provider import ModelProvider


logger = logging.getLogger(__name__)


class OllamaProvider(ModelProvider):
    def __init__(self, model="qwen3:8b", base_url="http://localhost:11434",
                 timeout=120.0, num_ctx=8192, num_predict=1400):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def generate(self, prompt: str) -> str:
        started = time.monotonic()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": 0,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        try:
            response = httpx.post(
                "{}/api/generate".format(self.base_url),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("Ollama request failed: {}".format(exc)) from exc
        finally:
            logger.info("Ollama model=%s elapsed_seconds=%.2f", self.model,
                        time.monotonic() - started)

        output = data.get("response") if isinstance(data, dict) else None
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("Ollama returned an empty or invalid response")
        return output
