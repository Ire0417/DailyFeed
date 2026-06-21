"""
ReportTemplate —— 报告的结构化模板层。

可替换的字段：
  {date}        → YYYY-MM-DD
  {total_items} → 整数
  {total_sources} → 整数
  {sections}    → 预渲染好的章节 Markdown（由 ReportBuilder 传入）

目前提供两套预设：
  DEFAULT  —— 标准每日摘要（带统计信息）
  NEWSLETTER —— 更像邮件推送的简洁排版

用户可通过 `set_custom()` 注入自定义模板，完全覆盖默认。
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict

_PRESETS: Dict[str, str] = {
    "default": (
        "# 每日摘要 - {date}\n\n"
        "本期共收录 **{total_items}** 条更新，来自 **{total_sources}** 个订阅源。\n\n"
        "{sections}\n\n"
        "---\n"
        "_由 DailyFeed 自动生成 · {now}_\n"
    ),
    "newsletter": (
        "# 每日资讯 - {date}\n\n"
        "{total_items} 条更新 · 来自 {total_sources} 个订阅源\n\n"
        "{sections}\n\n"
        "—\n"
        "Powered by DailyFeed\n"
    ),
    "zh_minimal": (
        "## {date}\n\n{sections}\n\n—— {total_items} 条 · {total_sources} 个源\n"
    ),
}

_custom: Dict[str, str] = {}


def list_presets() -> list[str]:
    return sorted(list(_PRESETS.keys()) + list(_custom.keys()))


def get_template(name: str = "default") -> str:
    if name in _custom:
        return _custom[name]
    return _PRESETS.get(name) or _PRESETS["default"]


def set_custom(name: str, template_text: str) -> None:
    """注册自定义模板。{date}/{total_items}/{total_sources}/{sections} 会被替换。"""
    _custom[name] = template_text


def render(name: str, *, sections: str, total_items: int, total_sources: int) -> str:
    tmpl = get_template(name)
    now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return tmpl.format(
        date=_dt.date.today().isoformat(),
        total_items=int(total_items),
        total_sources=int(total_sources),
        sections=sections or "",
        now=now,
    )


class ReportTemplate:
    """对象式 API，方便与 ReportBuilder 组合。"""

    def __init__(self, name: str = "default"):
        self.name = name

    def render(self, sections: str, total_items: int, total_sources: int) -> str:
        return render(self.name, sections=sections,
                      total_items=total_items, total_sources=total_sources)
