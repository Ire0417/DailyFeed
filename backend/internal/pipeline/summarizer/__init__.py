"""
摘要器入口。根据配置自动选择：
- 配置了 LLM API key -> 使用 `LLMSummarizer`
- 否则 -> 回退到 `ExtractiveSummarizer`
"""
from __future__ import annotations

from internal.infrastructure.monitoring.logger import get_logger
from internal.config.settings import settings
from internal.pipeline.summarizer.extractive import ExtractiveSummarizer
from internal.pipeline.summarizer.llm import LLMSummarizer, LLMResult
from internal.pipeline.summarizer.provider import build_provider, ProviderError


logger = get_logger("summarizer_factory")


def get_summarizer():
    """根据 settings 返回一个摘要器实例（LLM 或抽取式）。

    返回的对象保证有 `async def summarize(content, *, title="", source="")` 接口。
    """
    if not settings.llm_enabled:
        logger.info("LLM 摘要未启用，使用抽取式摘要器")
        return _ExtractiveWrapper()

    try:
        provider = build_provider(
            provider_name=settings._resolved_llm_provider,
            api_key=settings._resolved_llm_api_key,
            base_url=settings.llm_base_url,
            model=settings._resolved_llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    except (ProviderError, Exception) as exc:
        logger.error("构建 LLM provider 失败 (%s): %s。回退到抽取式摘要器",
                     settings._resolved_llm_provider, exc)
        return _ExtractiveWrapper()

    logger.info("LLM 摘要已启用: provider=%s model=%s",
                settings._resolved_llm_provider, provider.model or "")
    return LLMSummarizer(
        provider,
        max_chars=settings.llm_max_chars,
        max_tokens=settings.llm_max_tokens,
        enable_fallback=True,
    )


class _ExtractiveWrapper:
    """让 ExtractiveSummarizer 暴露与 LLMSummarizer 一致的接口。"""

    def __init__(self):
        self._impl = ExtractiveSummarizer()

    async def summarize(self, content: str, *, title: str = "",
                         source: str = "", **kwargs) -> LLMResult:
        text = await self._impl.summarize(content or "", top_n=3)
        if not text:
            text = (title or (content or "")[:200]).strip()
        return LLMResult(
            summary=text,
            provider="extractive",
            model="rule-based",
            tokens_in=0,
            tokens_out=0,
            tokens_total=0,
            duration_ms=0,
            fallback_to_extractive=False,
            error=None,
        )


__all__ = ["get_summarizer", "LLMResult", "LLMSummarizer", "ExtractiveSummarizer"]
