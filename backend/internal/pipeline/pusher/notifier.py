"""
Notifier - routes notifications to one or more configured channels.
"""
import asyncio
from internal.infrastructure.monitoring.logger import get_logger
from .email import EmailPusher
from .wechat import WeChatPusher, DingtalkPusher

logger = get_logger("notifier")


class Notifier:
    """
    Usage:
        notifier = Notifier(["email", "wechat", "dingtalk"])
        await notifier.notify(title, content, email_recipients=[...])
    """

    _registry = {
        "email": EmailPusher,
        "wechat": WeChatPusher,
        "dingtalk": DingtalkPusher,
    }

    def __init__(self, channels: list[str] | None = None):
        self.channels = channels or ["email"]
        self._email = EmailPusher()
        self._wechat = WeChatPusher()
        self._dingtalk = DingtalkPusher()

    async def notify(
        self,
        title: str,
        content: str,
        html_body: str | None = None,
        email_recipients: list[str] | None = None,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        tasks = []
        for ch in self.channels:
            if ch == "email":
                recipients = email_recipients or []
                if recipients:
                    tasks.append(
                        ("email", self._email.push(recipients, title, content, html_body))
                    )
            elif ch == "wechat":
                tasks.append(("wechat", self._wechat.push(title, content)))
            elif ch == "dingtalk":
                tasks.append(("dingtalk", self._dingtalk.push(title, content)))

        for name, task in tasks:
            try:
                if asyncio.iscoroutine(task):
                    results[name] = await task
                else:
                    results[name] = bool(task)
            except Exception as exc:
                logger.error("channel %s failed: %s", name, exc)
                results[name] = False
        return results
