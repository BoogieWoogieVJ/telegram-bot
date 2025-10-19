# middlewares/auto_delete.py

from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram import types
import logging

logger = logging.getLogger(__name__)

DELETE_COMMANDS = {"/menu", "/start"}
DELETE_BUTTON_TEXTS = {"📦 архив", "❓ помощь"} 

def norm(s: str) -> str:
    return (s or "").strip().casefold()

class AutoDeleteCommandsMiddleware(BaseMiddleware):
    async def on_process_message(self, message: types.Message, data: dict):
        txt = (message.text or "").strip()
        if not txt:
            return

        first = txt.split()[0]  # первое "слово" (для /команд)
        should_delete = (
            first in DELETE_COMMANDS                      # /menu, /start, ...
            or norm(txt) in {norm(t) for t in DELETE_BUTTON_TEXTS}  # "📦 Архив", "❓ Помощь"
        )

        if should_delete:
            try:
                await message.delete()
                logger.debug(f"Удалено: {txt!r}")
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение: {e}")