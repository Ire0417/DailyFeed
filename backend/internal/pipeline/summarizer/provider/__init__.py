from .base import BaseProvider, LLMResponse, ProviderError
from .http import OpenAIProvider, DeepSeekProvider, QwenProvider, HTTPProvider


__all__ = [
    "BaseProvider",
    "LLMResponse",
    "ProviderError",
    "HTTPProvider",
    "OpenAIProvider",
    "DeepSeekProvider",
    "QwenProvider",
]


PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
}


def build_provider(provider_name: str, **kwargs) -> BaseProvider:
    cls = PROVIDER_MAP.get(provider_name.lower())
    if not cls:
        raise ProviderError(
            f"未知的 LLM provider: {provider_name!r}. "
            f"支持: {sorted(PROVIDER_MAP.keys())}"
        )
    return cls(**kwargs)
