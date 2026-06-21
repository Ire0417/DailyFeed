"""
LLM Summarizer —— 基于大模型的内容摘要。

使用方式：
    provider = build_provider("openai", api_key="sk-...")
    sum_ = LLMSummarizer(provider)
    result = await sum_.summarize("长文本内容", title="文章标题", source="RSS")

特点：
- 语言自适应（根据输入内容判断中英文 prompt）
- 调用失败时自动回退到 `ExtractiveSummarizer`
- 返回 `LLMResult` dataclass，含 token/duration/provider 信息
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from internal.infrastructure.monitoring.logger import get_logger
from internal.pipeline.summarizer.extractive import ExtractiveSummarizer
from internal.pipeline.summarizer.provider import BaseProvider, LLMResponse
from internal.pipeline.summarizer.cache import SummaryCache, default_cache

logger = get_logger("llm_summarizer")


@dataclass
class LLMResult:
    summary: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_total: int
    duration_ms: int
    fallback_to_extractive: bool = False
    error: str | None = None


# -------- Prompt Templates --------

_SYS_EN = (
    "You are a concise content summarizer. Produce a neutral, factual summary "
    "in the same language as the input. Capture the core claim, key evidence, "
    "and the most important details. Do NOT repeat the title verbatim. "
    "Output 2-5 sentences, ~150-250 words. No preamble, no markdown."
)

_SYS_ZH = (
    "你是一名简洁的内容摘要助手。用与输入相同的语言输出，保持中立、事实性。"
    "提炼核心观点、关键证据和最重要的细节。不要逐字复述标题。"
    "输出 2-5 个句子，约 100-200 字。不要加开场白，不要用 Markdown。"
)

_USER_TEMPLATE_ZH = """请为以下内容生成摘要：
--- 标题 ---
{title}
--- 来源 ---
{source}
--- 正文 ---
{body}
--- END ---
直接输出摘要，不要任何额外说明。"""

_USER_TEMPLATE_EN = """Please summarize the following content:
--- Title ---
{title}
--- Source ---
{source}
--- Body ---
{body}
--- END ---
Output the summary directly with no extra commentary."""


def _looks_chinese(text: str) -> bool:
    """简单判断：文本中 >= 10% 的字符为中文 CJK。"""
    if not text:
        return False
    total = len(text)
    zh = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return zh / total > 0.1


def _truncate(text: str, max_chars: int = 12000) -> str:
    """截断超长内容，避免超出 LLM context。"""
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " ...[truncated]"


class LLMSummarizer:
    """基于大模型的摘要器。调用失败时回退到抽取式摘要。"""

    def __init__(self, provider: BaseProvider, *, max_chars: int = 12000,
                 max_tokens: int = 600, enable_fallback: bool = True,
                 cache: SummaryCache | None = None):
        self.provider = provider
        self.max_chars = max_chars
        self.max_tokens = max_tokens
        self.enable_fallback = enable_fallback
        self._extractive = ExtractiveSummarizer()
        self._cache = cache or default_cache()

    # ---- Public ----
    async def summarize(self, content: str, *, title: str = "",
                        source: str = "", **kwargs) -> LLMResult:
        title = (title or "").strip()
        source = (source or "unknown").strip()
        body = _truncate((content or "").strip(), self.max_chars)

        # Cache 先查
        cached = self._cache.get(title, content or body)
        if cached:
            logger.debug("llm summarizer cache hit: title=%r", title)
            return LLMResult(
                summary=cached["summary"],
                provider=cached["provider"] + "+cache",
                model="",
                tokens_in=0, tokens_out=0, tokens_total=0,
                duration_ms=0,
            )

        # 如果正文极短，直接返回原文作为摘要
        if len(body) < 80:
            result = LLMResult(
                summary=body or title,
                provider=self.provider.name,
                model=self.provider.model or "",
                tokens_in=0, tokens_out=0, tokens_total=0,
                duration_ms=0,
            )
            self._cache.put(title, content or body,
                             summary_text=result.summary,
                             provider=result.provider,
                             tokens_total=0, duration_ms=0)
            return result

        messages = self._build_messages(title, source, body)
        try:
            resp: LLMResponse = await self.provider.call(
                messages,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", 0.3),
            )
        except Exception as exc:
            logger.error("llm call raised: %s", exc)
            resp = LLMResponse(
                provider=self.provider.name,
                model=self.provider.model or "",
                error=str(exc),
            )

        if resp.ok:
            out = LLMResult(
                summary=self._clean(resp.text),
                provider=resp.provider,
                model=resp.model,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                tokens_total=resp.tokens_total,
                duration_ms=resp.duration_ms,
                error=None,
            )
            self._cache.put(title, content or body,
                             summary_text=out.summary, provider=out.provider,
                             tokens_total=out.tokens_total, duration_ms=out.duration_ms)
            return out

        # 失败：要么回退到抽取式，要么带着 error 返回
        logger.warning(
            "llm summary failed (provider=%s, err=%s), fallback=%s",
            self.provider.name, resp.error, self.enable_fallback,
        )
        if self.enable_fallback:
            text = await self._extractive.summarize(body, top_n=3)
            return LLMResult(
                summary=text or title or body[:200],
                provider=resp.provider,
                model=resp.model,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                tokens_total=resp.tokens_total,
                duration_ms=resp.duration_ms,
                fallback_to_extractive=True,
                error=resp.error,
            )
        return LLMResult(
            summary=title or body[:200],
            provider=resp.provider,
            model=resp.model,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            tokens_total=resp.tokens_total,
            duration_ms=resp.duration_ms,
            fallback_to_extractive=False,
            error=resp.error,
        )

    # ---- helpers ----
    def _build_messages(self, title: str, source: str, body: str) -> list[dict]:
        zh = _looks_chinese(body + " " + title)
        sys_prompt = _SYS_ZH if zh else _SYS_EN
        tmpl = _USER_TEMPLATE_ZH if zh else _USER_TEMPLATE_EN
        return [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": tmpl.format(title=title or "(无标题)", source=source, body=body),
            },
        ]

    @staticmethod
    def _clean(text: str) -> str:
        if not text:
            return ""
        # 去掉首尾引号 / 多余换行
        text = text.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "“", "”"):
            text = text[1:-1].strip()
        # 折叠空白
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
