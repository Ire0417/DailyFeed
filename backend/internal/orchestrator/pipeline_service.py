"""
PipelineService - 同步执行报告生成的主服务。

独立模块不依赖消息总线或 agent 进程，所有抓取/聚合/摘要 / 摘要和推送全部在同一进程内完成。适用于:
- 前端页面 "立即生成一次" 按钮
- 测试脚本 直接调用 API 得到报告
"""
from __future__ import annotations

import datetime
import asyncio
from typing import Any

from sqlalchemy.orm import Session

from internal.config.settings import settings
from internal.infrastructure.database.models import SubscriptionModel, ContentModel, SummaryModel, ReportModel
from internal.infrastructure.database.repositories.subscription_repo import SubscriptionRepository
from internal.infrastructure.database.repositories.content_repo import ContentRepository
from internal.infrastructure.database.repositories.report_repo import ReportRepository
from internal.infrastructure.database.repositories.user_repo import UserRepository
from internal.infrastructure.monitoring.logger import get_logger

# ---------- Memory Module ----------
from internal.memory import (
    get_memory_router,
    get_lifecycle_manager,
    MemoryKind,
    MemoryImportance,
    AccessLevel,
    LAYER_GLOBAL,
    LAYER_SESSION,
    LAYER_TASK,
)

logger = get_logger("pipeline_service")


class PipelineService:
    """
    同步报告生成服务（不依赖 Redis / 消息总线）。

    使用方法:
        service = PipelineService(db_session)
        report = await service.run_pipeline(user_id=1)
        print(report.id, report.title)
    """

    def __init__(self, db: Session):
        self.db = db
        self.sub_repo = SubscriptionRepository(db)
        self.user_repo = UserRepository(db)
        self.report_repo = ReportRepository(db)
        # --- Memory integration ---
        self.memory = get_memory_router(db)
        self.memory.declare_agent(
            "pipeline_service",
            global_shared=AccessLevel.READ_WRITE,
            session_isolated=AccessLevel.READ_WRITE,
            task_specific=AccessLevel.READ_WRITE,
        )
        # 生命周期管理器：可选启动后台线程
        try:
            self.lifecycle = get_lifecycle_manager(db, auto_start=False)
        except Exception as exc:
            logger.warning("pipeline: lifecycle manager init exc=%s", exc)
            self.lifecycle = None
        logger.info("pipeline_service: 已接入三层记忆模块")

    # ---------------- Public API ----------------
    async def run_pipeline(
        self,
        user_id: int,
        *,
        include_inactive: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        运行一次完整流水线: 抓取 → 摘要 → 聚合 → 推送。

        Returns:
            { report_id, title, stats, pushed_channels, error (if any)
        """
        start = datetime.datetime.utcnow()
        stats = {
            "subscriptions": 0,
            "contents_fetched": 0,
            "summaries_generated": 0,
            "sources": {},
        }

        # --- Memory: 启动任务上下文 ---
        task_id = self.memory.start_task("pipeline_service", user_id=user_id,
                                          agent_name="pipeline_service")
        try:
            pref = self.memory.get_preference(user_id, agent_name="pipeline_service")
            stats["preference"] = {
                "like_keywords": list(getattr(pref, "like_keywords", []) or []),
                "channels": list(getattr(pref, "preferred_channels", []) or []),
                "style": getattr(pref, "summary_style", "balanced"),
            }
            self.memory.log_step(task_id, "init", f"加载用户偏好完成，{len(stats['preference']['like_keywords'])} 个关键词",
                                 payload={"user_id": user_id}, agent_name="pipeline_service")
        except Exception as exc:
            logger.warning("pipeline: memory init exc=%s", exc)
            task_id = task_id or "mem-disabled"

        # 1) 取得用户订阅
        subs = self.sub_repo.list_by_user(user_id=user_id, only_active=not include_inactive)
        stats["subscriptions"] = len(subs)
        logger.info("pipeline: user=%s subscriptions=%s", user_id, len(subs))

        if not subs:
            try:
                self.memory.log_step(task_id, "skip", "无订阅源", agent_name="pipeline_service")
            except Exception:
                pass
            return self._empty_report(user_id, "没有订阅源，无法生成报告")

        # 2) 抓取每个订阅源
        contents_by_sub: dict[int, list[ContentModel]] = {}
        all_keywords: list[str] = []
        for sub in subs:
            try:
                items = await self._fetch_subscription(sub)
                contents_by_sub[sub.id] = items
                stats["sources"][str(sub.id)] = {
                    "source_type": sub.source_type,
                    "count": len(items),
                }
                stats["contents_fetched"] += len(items)
                # 收集内容中的关键词（取 title 里的 token）
                for item in items:
                    title = getattr(item, "title", "") or ""
                    tokens = [t for t in title.replace("/", " ").replace("-", " ").split()
                              if t and len(t) >= 2][:5]
                    all_keywords.extend(tokens)
                try:
                    self.memory.log_step(
                        task_id, "fetch",
                        f"{sub.source_type}({sub.source_url or 'default'}) 抓取 {len(items)} 条",
                        payload={"source_type": sub.source_type, "count": len(items)},
                        agent_name="pipeline_service",
                    )
                except Exception:
                    pass
            except Exception as exc:
                logger.error("pipeline: fetch failed sub=%s exc=%s", sub.id, exc)
                stats["sources"][str(sub.id)] = {"source_type": sub.source_type, "count": 0, "error": str(exc)}
        logger.info("pipeline: fetched %s contents total", stats["contents_fetched"])

        # --- Memory: 把关键词写入 GraphMem（如果收集到了）---
        if all_keywords:
            unique_kw = list(dict.fromkeys(all_keywords))[:30]
            try:
                self.memory.add_cooccurrence(unique_kw, kind="keyword",
                                              agent_name="pipeline_service")
                logger.info("pipeline: 写入 graph memory %s 关键词", len(unique_kw))
            except Exception as exc:
                logger.warning("pipeline: graph mem write exc=%s", exc)

        # 3) 摘要（若 LLM 可用则用 LLM，否则抽取式摘要）
        try:
            summaries = await self._summarize_contents(contents_by_sub)
            stats["summaries_generated"] = len(summaries)
            try:
                self.memory.log_step(task_id, "summarize", f"完成 {len(summaries)} 条摘要",
                                     payload={"count": len(summaries)},
                                     agent_name="pipeline_service")
            except Exception:
                pass
        except Exception as exc:
            logger.error("pipeline: summarize failed exc=%s", exc)
            summaries = []

        # 4) 聚合报告
        try:
            report_body = await self._build_report_markdown(subs, summaries)
            html_body = self._markdown_to_simple_html(report_body)
        except Exception as exc:
            logger.error("pipeline: aggregate failed exc=%s", exc)
            report_body = "(报告生成失败)"
            html_body = "(报告生成失败)"

        # 5) 保存到数据库
        report = self._save_report(user_id=user_id, title="每日摘要 - " + datetime.date.today().isoformat(),
                                    markdown_body=report_body, html_body=html_body, stats=stats, status="ready")
        logger.info("pipeline: saved report id=%s", report.id)

        # --- Memory: 报告完成后写入 LongTermMemory ---
        try:
            summary_preview = (report_body or "")[:400]
            self.memory.remember_long_term(
                MemoryKind.LTM,
                content=f"[report-{report.id}] {report.title} — {summary_preview}",
                user_id=user_id,
                tags=["report", datetime.date.today().isoformat()] + [f"sub-{s.id}" for s in subs][:5],
                importance=MemoryImportance.HIGH,
                ttl_seconds=60 * 60 * 24 * 30,
                agent_name="pipeline_service",
            )
            self.memory.log_step(task_id, "aggregate",
                                 f"报告已生成 id={report.id} title={report.title}",
                                 payload={"report_id": report.id, "title": report.title},
                                 agent_name="pipeline_service")
        except Exception as exc:
            logger.warning("pipeline: ltm write exc=%s", exc)

        # 6) 推送（按需）
        pushed = []
        try:
            pushed = await self._push_report(report, user_id)
            if pushed:
                self.report_repo.update_status(report.id, "delivered")
            try:
                self.memory.log_step(task_id, "push",
                                     f"推送渠道 {'/'.join(pushed) if pushed else '无'}",
                                     payload={"channels": pushed},
                                     agent_name="pipeline_service")
            except Exception:
                pass
        except Exception as exc:
            logger.error("pipeline: push failed exc=%s", exc)

        elapsed = (datetime.datetime.utcnow() - start).total_seconds()
        logger.info("pipeline: completed in %ss channels=%s", elapsed, pushed)

        return {
            "report_id": report.id,
            "title": report.title,
            "stats": stats,
            "pushed_channels": pushed,
            "seconds": round(elapsed, 2),
        }

    # ---------------- Helpers ----------------
    async def _fetch_subscription(self, sub: SubscriptionModel) -> list[ContentModel]:
        """根据订阅源类型调用对应抓取逻辑，直接写入数据库并返回内容列表。"""
        source_type = (sub.source_type or "").lower().strip()
        source_url = (sub.source_url or "").strip()
        items_raw = []

        if source_type == "github":
            from internal.pipeline.fetcher.github import fetch as gh_fetch
            items_raw = await self._safe_call(gh_fetch, source_url, limit=10)
        elif source_type == "rss":
            from internal.pipeline.fetcher.rss import fetch as rss_fetch
            items_raw = await self._safe_call(rss_fetch, source_url, limit=10)
        elif source_type == "bilibili":
            from internal.pipeline.fetcher.bilibili import fetch as bili_fetch
            items_raw = await self._safe_call(bili_fetch, source_url, limit=5)
        else:
            logger.warning("pipeline: unsupported source_type=%s", source_type)
            return []

        saved_items: list[ContentModel] = []
        for it in items_raw or []:
            try:
                title = str(it.get("title") or "(无标题)")
                url_val = str(it.get("url") or "")
                content = str(it.get("raw_content") or it.get("content") or "")
                external_id = str(it.get("external_id") or url_val or title)
                published_at = it.get("published_at") or datetime.datetime.utcnow()
                # 去重: 按 subscription + title
                existing = self.db.query(ContentModel).filter(
                    ContentModel.subscription_id == sub.id,
                    ContentModel.title == title[:512]
                ).first()
                if existing:
                    continue
                c = ContentModel(
                    subscription_id=sub.id,
                    title=title[:512],
                    author=str(it.get("author") or "")[:128],
                    raw_content=content[:65535] if content else "",
                    url=url_val[:1024],
                    content_hash=str(hash(external_id))[:128],
                    published_at=published_at,
                    fetched_at=datetime.datetime.utcnow(),
                )
                self.db.add(c)
                self.db.flush()
                saved_items.append(c)
            except Exception as exc:
                logger.error("pipeline: save content failed exc=%s", exc)
        self.db.commit()
        return saved_items

    async def _safe_call(self, coro_func, *args, **kwargs):
        """调用抓取函数，含超时/异常回退。"""
        try:
            return await coro_func(*args, **kwargs)
        except Exception as exc:
            logger.error("pipeline: fetch call failed exc=%s", exc)
            return []

    async def _summarize_contents(self, contents_by_sub: dict[int, list[ContentModel]]) -> list[dict]:
        """对每个内容生成摘要，返回 [{subscription_id, content_id, title, url, summary, published_at, author}]。"""
        summarizer = _get_summarizer()
        results: list[dict] = []

        for sub_id, items in contents_by_sub.items():
            for c in items:
                text = c.raw_content or ""
                title = c.title or ""
                summary_text = ""
                try:
                    if summarizer and text:
                        result = summarizer.summarize(text, title=title, source="web")
                        if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                            result = await result
                        summary_text = (
                            getattr(result, "summary_text", None)
                            or getattr(result, "summary", "")
                            or str(result)
                        )
                    else:
                        # fallback: 取前 200 字
                        summary_text = (text or "")[:200]
                except Exception:
                    summary_text = (text or "")[:200]

                results.append({
                    "subscription_id": sub_id,
                    "content_id": c.id,
                    "title": title,
                    "url": c.url,
                    "summary": summary_text or "(无法生成摘要)",
                    "published_at": c.published_at,
                    "author": c.author,
                })

        return results

    async def _build_report_markdown(self, subs: list[SubscriptionModel], summaries: list[dict]) -> str:
        """用聚合报告模板（按订阅源分组）。"""
        from internal.pipeline.aggregator.report_builder import ReportBuilder
        builder = ReportBuilder()
        grouped: dict[str, list[dict]] = {}
        sub_map = {s.id: s for s in subs}
        for s in summaries:
            sub = sub_map.get(s["subscription_id"])
            label = _source_label(sub)
            grouped.setdefault(label, []).append(s)
        report_body = await builder.build(grouped)
        return report_body["markdown_body"]

    def _markdown_to_simple_html(self, md: str) -> str:
        """极简 Markdown → HTML 渲染。"""
        import re
        html = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = html.splitlines()
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("### "):
                out.append(f"<h3>{stripped[4:]}</h3>")
            elif stripped.startswith("## "):
                out.append(f"<h2>{stripped[3:]}</h2>")
            elif stripped.startswith("# "):
                out.append(f"<h1>{stripped[2:]}</h1>")
            elif stripped.startswith("- "):
                out.append(f"<li>{stripped[2:]}</li>")
            elif stripped.startswith("> "):
                out.append(f"<blockquote>{stripped[2:]}</blockquote>")
            elif stripped == "":
                out.append("<br/>")
            else:
                out.append(f"<p>{stripped}</p>")
        return "<html><body style=\"font-family:sans-serif;\">" + "\n".join(out) + "</body></html>"

    def _save_report(self, *, user_id: int, title: str, markdown_body: str,
                       html_body: str, stats: dict, status: str) -> ReportModel:
        today = datetime.date.today()
        existing = self.report_repo.get_by_date(user_id=user_id, report_date=today)
        if existing:
            existing.title = title
            existing.markdown_body = markdown_body
            existing.html_body = html_body
            existing.stats = stats
            existing.status = status
            self.db.commit()
            return existing
        report = ReportModel(
            user_id=user_id,
            report_date=today,
            title=title,
            markdown_body=markdown_body,
            html_body=html_body,
            stats=stats,
            status=status,
            created_at=datetime.datetime.utcnow(),
        )
        return self.report_repo.create(report)

    async def _push_report(self, report: ReportModel, user_id: int) -> list[str]:
        """根据用户设置推送报告。"""
        from internal.pipeline.pusher.email import EmailPusher
        pushed: list[str] = []
        user = self.user_repo.get_by_id(user_id)
        user_settings = user.settings or {}

        channels = user_settings.get("channels") or ["email"]
        recipients = user_settings.get("email_recipients") or [user.email]

        if not recipients or not recipients:
            recipients = [user.email]

        if "email" in channels:
            pusher = EmailPusher()
            try:
                ok = await pusher.push(
                    recipients=recipients,
                    subject=report.title,
                    body=report.markdown_body or "",
                    html_body=report.html_body,
                )
                if ok:
                    pushed.append("email")
                    self.report_repo.add_push_log(report.id, "email", "success")
            except Exception as exc:
                logger.error("pipeline: email push failed exc=%s", exc)
                self.report_repo.add_push_log(report.id, "email", "error", str(exc))
        return pushed

    def _empty_report(self, user_id: int, msg: str) -> dict:
        """当没有订阅源时返回。"""
        today = datetime.date.today()
        body = f"# 每日摘要 - {today.isoformat()}\n\n{msg}\n"
        html = self._markdown_to_simple_html(body)
        report = ReportModel(
            user_id=user_id,
            report_date=today,
            title="每日摘要 - " + today.isoformat(),
            markdown_body=body,
            html_body=html,
            stats={"subscriptions": 0},
            status="ready",
            created_at=datetime.datetime.utcnow(),
        )
        self.report_repo.create(report)
        return {
            "report_id": report.id,
            "title": report.title,
            "stats": report.stats,
            "pushed_channels": [],
            "seconds": 0,
        }


def _source_label(sub: SubscriptionModel | None) -> str:
    if not sub:
        return "其他"
    t = sub.source_type or "other"
    label = {"rss": "RSS", "github": "GitHub", "bilibili": "Bilibili"}.get(t, t.upper())
    return f"{label} ({sub.source_url})"


def _get_summarizer():
    """安全地获取摘要器（LLM 不可用时回退到抽取式）。"""
    try:
        from internal.pipeline.summarizer import get_summarizer as _gs
        return _gs()
    except Exception as exc:
        logger.warning("pipeline: summarizer unavailable exc=%s", exc)
        return None
