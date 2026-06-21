"""
Webhook pushers (WeChat Work / DingTalk group bots).
"""
import json
import hashlib
import time
import base64
import hmac
import urllib.request
import urllib.parse
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("webhook_pusher")


class WeChatPusher:
    async def push(self, title: str, content: str) -> bool:
        if not settings.wechat_webhook:
            logger.warning("wechat push skipped: webhook not configured")
            return False
        body = {
            "msgtype": "markdown",
            "markdown": {"content": f"### {title}\n\n{content}"},
        }
        return _post(settings.wechat_webhook, body, "wechat")


class DingtalkPusher:
    async def push(self, title: str, content: str) -> bool:
        if not settings.dingtalk_webhook:
            logger.warning("dingtalk push skipped: webhook not configured")
            return False

        url = settings.dingtalk_webhook
        secret = settings.dingtalk_secret
        if secret:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={timestamp}&sign={sign}"

        body = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"### {title}\n\n{content}"},
        }
        return _post(url, body, "dingtalk")


def _post(url: str, payload: dict, name: str) -> bool:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        logger.info("%s pushed", name)
        return True
    except Exception as exc:
        logger.error("%s push failed: %s", name, exc)
        return False
