"""LLM runtime adapters — detect and manage local LLM runtimes."""

from __future__ import annotations

import abc
import logging
import subprocess

import httpx

logger = logging.getLogger(__name__)


class RuntimeAdapter(abc.ABC):
    """Abstract base for LLM runtime adapters."""

    @abc.abstractmethod
    async def is_available(self) -> bool:
        ...

    @abc.abstractmethod
    async def list_models(self) -> list[str]:
        ...

    @abc.abstractmethod
    async def pull_model(self, model: str) -> bool:
        ...

    @abc.abstractmethod
    async def has_model(self, model: str) -> bool:
        ...


class OllamaAdapter(RuntimeAdapter):
    """Adapter for Ollama runtime."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/version")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []

    async def has_model(self, model: str) -> bool:
        models = await self.list_models()
        # Check exact match or base name match
        for m in models:
            if m == model or m.split(":")[0] == model.split(":")[0]:
                return True
        return False

    async def pull_model(self, model: str) -> bool:
        """Pull a model via Ollama API."""
        logger.info(f"Pulling Ollama model: {model}")
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": model, "stream": False},
                    timeout=600,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to pull model {model}: {e}")
            return False


async def detect_runtime() -> RuntimeAdapter | None:
    """Detect available LLM runtime on localhost."""
    ollama = OllamaAdapter()
    if await ollama.is_available():
        logger.info("Detected Ollama runtime")
        return ollama

    logger.info("No local LLM runtime detected")
    return None
