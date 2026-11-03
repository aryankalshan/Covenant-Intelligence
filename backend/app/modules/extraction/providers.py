import asyncio
from dataclasses import dataclass
from typing import Protocol, Sequence

import httpx


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    metadata: dict


class LLMProvider(Protocol):
    async def extract(self, messages: list[dict[str, str]], schema: dict) -> LLMResponse: ...


class OpenRouterProvider:
    def __init__(self, api_key: str, model: str, base_url: str, *, timeout_seconds: float = 45, max_retries: int = 2, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise ProviderError("provider_not_configured", "OpenRouter API key is not configured.")
        if not model:
            raise ProviderError("provider_not_configured", "OpenRouter model is not configured.")
        self._api_key = api_key
        self._model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._transport = transport

    async def extract(self, messages: list[dict[str, str]], schema: dict) -> LLMResponse:
        request_body = {
            "model": self._model,
            "messages": messages,
            "provider": {"require_parameters": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "covenant_extraction", "strict": True, "schema": schema},
            },
        }
        last_error: ProviderError | None = None
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post(
                        self._url,
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                        json=request_body,
                    )
                except httpx.TransportError as exc:
                    last_error = ProviderError("provider_transport_error", "OpenRouter request timed out or could not connect.")
                    if attempt < self._max_retries:
                        await asyncio.sleep(min(0.2 * (2 ** attempt), 1.0))
                        continue
                    raise last_error from exc

                if response.status_code == 429 or response.status_code >= 500:
                    if response.status_code == 429:
                        last_error = ProviderError(
                            "provider_rate_limited",
                            "OpenRouter rate limit exceeded (HTTP 429). Retry later.",
                            status_code=429,
                        )
                    else:
                        last_error = ProviderError(
                            "provider_temporary_error",
                            f"OpenRouter is temporarily unavailable (HTTP {response.status_code}).",
                            status_code=response.status_code,
                        )
                    if attempt < self._max_retries:
                        retry_after = response.headers.get("retry-after", "")
                        try:
                            delay = min(float(retry_after), 2.0) if retry_after else min(0.2 * (2 ** attempt), 1.0)
                        except ValueError:
                            delay = min(0.2 * (2 ** attempt), 1.0)
                        await asyncio.sleep(delay)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    if response.status_code == 402:
                        raise ProviderError(
                            "provider_insufficient_credits",
                            "OpenRouter reports insufficient credits (HTTP 402). Add credits or review account limits.",
                            status_code=402,
                        )
                    if response.status_code in {401, 403}:
                        raise ProviderError(
                            "provider_authentication_error",
                            f"OpenRouter authentication or model access failed (HTTP {response.status_code}). Verify local credentials and model access.",
                            status_code=response.status_code,
                        )
                    raise ProviderError(
                        "provider_request_rejected",
                        f"OpenRouter rejected the extraction request (HTTP {response.status_code}). Check model and request compatibility.",
                        status_code=response.status_code,
                    )
                try:
                    data = response.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise ProviderError("provider_response_invalid", "OpenRouter response did not contain structured message content.") from exc
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                if not isinstance(content, str):
                    raise ProviderError("provider_response_invalid", "OpenRouter response content was not text.")
                usage = data.get("usage") or {}
                metadata = {
                    "finish_reason": choice.get("finish_reason"),
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                }
                return LLMResponse(content=content, provider="openrouter", model=data.get("model", self._model), metadata=metadata)
        raise last_error or ProviderError("provider_error", "OpenRouter request failed.")


class MockLLMProvider:
    """Deterministic provider for tests; responses may be JSON text or intentionally invalid strings."""

    def __init__(self, responses: Sequence[str], *, provider_error: ProviderError | None = None):
        self._responses = list(responses)
        self._cursor = 0
        self.provider_error = provider_error
        self.calls: list[list[dict[str, str]]] = []

    async def extract(self, messages: list[dict[str, str]], schema: dict) -> LLMResponse:
        self.calls.append(messages)
        if self.provider_error:
            raise self.provider_error
        if self._cursor >= len(self._responses):
            raise ProviderError("mock_response_missing", "Mock provider has no queued response.")
        content = self._responses[self._cursor]
        self._cursor += 1
        return LLMResponse(content=content, provider="mock", model="mock/deterministic", metadata={"mock": True})
