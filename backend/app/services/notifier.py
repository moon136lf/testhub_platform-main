"""Notifier — P1 push placeholder. Stub now; later wire 钉钉/微信 webhook."""
import logging

logger = logging.getLogger(__name__)


class Notifier:
    async def notify_report_ready(self, exec_id: str, meta: dict):
        """P1 预留：本期仅日志；后期对接钉钉/微信 webhook。
        webhook 配置复用 #10 SystemSettingService（notify category）。"""
        logger.info(f"[notifier stub] report ready for {exec_id}: {meta}")


async def notify_report_ready(exec_id: str, meta: dict):
    """Module-level convenience helper."""
    await Notifier().notify_report_ready(exec_id, meta)
