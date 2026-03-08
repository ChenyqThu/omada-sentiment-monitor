"""LLM provider abstraction for AI batch filtering."""
import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return raw text completion."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for logging."""


class GeminiProvider(LLMProvider):
    """Google Gemini API provider. Supports custom base_url for third-party proxies."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-lite", base_url: str = None):
        try:
            from google import genai
        except ImportError:
            raise ImportError("google-genai package required: pip install google-genai")
        self._model = model
        kwargs = {"api_key": api_key}
        if base_url:
            from google.genai import types
            kwargs["http_options"] = types.HttpOptions(base_url=base_url)
        self._client = genai.Client(**kwargs)

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        from google.genai import types
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )
        return response.text


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible API provider (OpenAI, DeepSeek, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str = None):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required: pip install openai")
        self._model = model
        kwargs = {"api_key": api_key, "timeout": 120.0}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=8192,
        )
        return response.choices[0].message.content
