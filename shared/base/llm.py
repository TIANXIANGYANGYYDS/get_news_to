from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from openai import OpenAI

from shared.base.model import ModelBase
from shared.exceptions.errors import RetryableError

T = TypeVar("T", bound=ModelBase)


class BaseLLMClient(ABC):
    def __init__(self, *, api_key: str, base_url: str, model_name: str, timeout_seconds: int, max_retries: int):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self.model_name = model_name
        self.max_retries = max_retries

    def complete_json(self, prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(model=self.model_name, input=prompt)
                text = response.output_text
                return json.loads(text)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        raise RetryableError(f"llm request failed: {last_error}")


class BaseLLMAnalyzer(ABC):
    output_model: type[T]

    def __init__(self, llm_client: BaseLLMClient):
        self.llm_client = llm_client

    @abstractmethod
    def build_prompt(self, payload: ModelBase) -> str:
        raise NotImplementedError

    def fallback(self, payload: ModelBase, error: str) -> T:
        return self.output_model.from_dict({"is_fallback": True, "error_message": error})

    def analyze(self, payload: ModelBase) -> T:
        started = time.perf_counter()
        try:
            prompt = self.build_prompt(payload)
            raw_result = self.llm_client.complete_json(prompt)
            return self.output_model.from_dict(raw_result)
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            fallback = self.fallback(payload, str(exc))
            if hasattr(fallback, "latency_ms"):
                fallback.latency_ms = latency
            return fallback
