"""
Telegram alert sender.
Uses python-telegram-bot v20+ async API wrapped in asyncio.run().
"""

import os
import asyncio
import logging

log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


async def _send(message: str) -> None:
    try:
        import telegram
        bot = telegram.Bot(token=BOT_TOKEN)
        # Split long messages (Telegram limit = 4096 chars)
        for chunk in [message[i:i+4000] for i in range(0, len(message), 4000)]:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=chunk,
                parse_mode="HTML",
            )
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)


def send_alert(message: str) -> None:
    """Blocking wrapper — safe to call from sync code."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram env vars not set — printing alert to stdout instead.")
        print(message)
        return
    asyncio.run(_send(message))
