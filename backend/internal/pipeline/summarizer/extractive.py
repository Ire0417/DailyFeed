"""
Extractive summarizer - generate a concise summary without LLM access.

Phase 1 fallback: sentence-based scoring. When `openai_api_key` is configured
in settings, an LLM summarizer is preferred instead (see llm.py).
"""
import re
from collections import Counter
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("extractive_summarizer")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "of",
    "on", "at", "in", "to", "from", "by", "with", "is", "are", "was", "were",
    "be", "been", "being", "it", "this", "that", "these", "those", "as", "so",
    "than", "such", "i", "you", "he", "she", "we", "they", "them", "his",
    "her", "their", "our", "my", "your", "me", "him", "us", "has", "have",
    "had", "do", "does", "did", "not", "no", "yes", "also", "just", "more",
    "most", "some", "any", "all", "can", "will", "would", "could", "should",
    "may", "might", "shall",
    "的", "了", "和", "是", "在", "我", "有", "他", "她", "它", "们", "这",
    "那", "个", "一", "不", "与", "及", "等", "也", "都", "就", "而", "或",
    "以", "于", "被", "将", "会", "要", "对", "之", "其", "为", "着", "给",
    "让", "把", "从", "到", "向", "由", "中", "上", "下",
}


def _split_sentences(text: str) -> list[str]:
    # Split on . ! ? and Chinese equivalents.
    pieces = re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", text)
    return [p.strip() for p in pieces if p and len(p.strip()) > 0]


def _tokens(text: str) -> list[str]:
    # Naive tokenizer: lowercase letters for English; keep Chinese chars as-is.
    lowered = text.lower()
    words = re.findall(r"[a-z0-9']+|[\u4e00-\u9fff]", lowered)
    return [w for w in words if w not in _STOPWORDS]


class ExtractiveSummarizer:
    async def summarize(self, content: str, top_n: int = 3) -> str:
        text = (content or "").strip()
        if not text:
            return ""

        sentences = _split_sentences(text)
        if not sentences:
            return text[:200]

        if len(sentences) <= top_n:
            return " ".join(sentences)

        all_tokens = _tokens(text)
        freq = Counter(all_tokens)
        total = sum(freq.values()) or 1

        scored: list[tuple[float, int, str]] = []
        for idx, sentence in enumerate(sentences):
            tokens = _tokens(sentence)
            if not tokens:
                continue
            score = sum(freq.get(t, 0) / total for t in tokens) / len(tokens)
            # Favor earlier sentences slightly (position bias)
            position_bonus = max(0.0, 1.0 - 0.05 * idx)
            scored.append((score * position_bonus, idx, sentence))

        scored.sort(key=lambda s: (-s[0], s[1]))
        top = scored[:top_n]
        top.sort(key=lambda s: s[1])

        summary = " ".join(s[2] for s in top)
        return summary.strip()
