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

MAX_CHUNK = 3800  # conservative limit below Telegram 4096-char cap


async def _send(message: str) -> None:
    try:
        import telegram
        bot = telegram.Bot(token=BOT_TOKEN)
        # Split at newline boundaries â never mid-HTML-tag.
        # Naive char-based split (message[i:i+4000]) can cut inside
        # <a href="..."> URLs, causing Telegram to reject with
        # "Can't parse entities: unclosed start tag".
        chunks = []
        current = ""
        for line in message.split("\n"):
            candidate = current + line + "\n"
            if len(candidate) > MAX_CHUNK and current:
                chunks.append(current.rstrip("\n"))
                current = line + "\n"
            else:
                current = candidate
        if current:
            chunks.append(current.rstrip("\n"))

        for chunk in chunks:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=chunk,
                parse_mode="HTML",
            )
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)


def send_alert(message: str) -> None:
    """Blocking wrapper â safe to call from sync code."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram env vars not set â printing alert to stdout instead.")
        print(message)
        return
    asyncio.run(_send(message))
