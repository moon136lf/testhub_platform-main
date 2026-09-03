"""Notifier — 报告就绪推送。

支持 webhook 渠道：钉钉 / 企业微信 / 飞书 / 自定义 HTTP。
webhook 地址从 system_setting（category='notify'）读取，键名：
  notify.dingtalk_webhook / notify.wecom_webhook / notify.feishu_webhook /
  notify.custom_webhook
未配置任何 webhook 时降级为日志（保持旧行为），并返回 pushed=False 供前端如实提示。
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)

# 渠道名 -> (设置键, 默认判定成功关键词)；custom 不判关键词
_WEBHOOK_CHANNELS = {
    "dingtalk": ("notify.dingtalk_webhook", "errcode"),
    "wecom": ("notify.wecom_webhook", "errcode"),
    "feishu": ("notify.feishu_webhook", "code"),
    "custom": ("notify.custom_webhook", None),
}


class Notifier:
    async def _get_webhook(self, key: str) -> str | None:
        """从 system_setting 读 webhook 地址（notify 类，含加密值解密）。"""
        async with AsyncSessionLocal() as db:
            return await SystemSettingService(db).get(key, category="notify")

    async def notify_report_ready(self, exec_id: str, meta: dict) -> dict:
        """向所有已配置的 webhook 推送报告就绪消息。

        Returns:
            {"pushed": bool, "channels": {channel: "ok"|"error: ..."...}}
            全部未配置时 pushed=False（前端如实提示，不再假成功）。
        """
        payload = {
            "event": "report_ready",
            "exec_id": exec_id,
            **(meta or {}),
        }
        text = f"MoonTest 报告就绪：{exec_id}"

        results = {}
        sent = False
        for channel, (key, ok_field) in _WEBHOOK_CHANNELS.items():
            try:
                url = await self._get_webhook(key)
            except Exception as e:
                logger.warning(f"notify config read failed for {key}: {e}")
                url = None
            if not url:
                continue

            try:
                body = self._build_body(channel, text, payload)
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=body)
                    resp.raise_for_status()
                # 渠道返回体业务校验（钉钉/企微 errcode==0）
                if ok_field:
                    try:
                        rj = resp.json()
                        if rj.get(ok_field) not in (0, 200, None):
                            results[channel] = f"error: upstream {ok_field}={rj.get(ok_field)}"
                            continue
                    except ValueError:
                        pass
                results[channel] = "ok"
                sent = True
                logger.info(f"【报告推送】推送成功 | 渠道={channel} exec={exec_id}")
            except Exception as e:
                logger.error(f"【报告推送】推送失败 | 渠道={channel} exec={exec_id} 原因={e} 建议=检查webhook地址可达性")
                results[channel] = f"error: {e}"

        if not results:
            logger.info(f"【报告推送】未配置webhook渠道，跳过推送 | exec={exec_id} 建议=在系统设置(category=notify)配置钉钉/企微/飞书Webhook")
        return {"pushed": sent, "channels": results}

    def _build_body(self, channel: str, text: str, payload: dict) -> dict:
        """按渠道构造消息体；custom 渠道直接发统一 JSON。"""
        if channel == "dingtalk":
            return {"msgtype": "text", "text": {"content": f"[MoonTest] {text}"}}
        if channel == "wecom":
            return {"msgtype": "text", "text": {"content": f"[MoonTest] {text}"}}
        if channel == "feishu":
            return {"msg_type": "text", "content": {"text": f"[MoonTest] {text}"}}
        return {"text": text, **payload}


async def notify_report_ready(exec_id: str, meta: dict) -> dict:
    """Module-level convenience helper."""
    return await Notifier().notify_report_ready(exec_id, meta)
