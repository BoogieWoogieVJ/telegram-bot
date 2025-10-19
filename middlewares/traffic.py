import hashlib
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram import types
import logging

logger = logging.getLogger(__name__)

def anon_id(user_id: int) -> str:
    """Анонимизируем user_id: одинаковые пользователи -> одинаковый короткий хэш."""
    return hashlib.sha1(str(user_id).encode()).hexdigest()[:8]

class TrafficLogMiddleware(BaseMiddleware):
    def __init__(self, log_payload: bool = False):
        super().__init__()
        self.log_payload = log_payload

    async def on_process_message(self, message: types.Message, data: dict):
        uid = anon_id(message.from_user.id)
        if self.log_payload:
            logger.info(f"MSG from {uid}: text={message.text!r}")
        else:
            logger.info(f"MSG from {uid}: len={len(message.text or '')}")

    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        uid = anon_id(call.from_user.id)
        if self.log_payload:
            logger.info(f"CB from {uid}: data={call.data!r}")
        else:
            logger.info(f"CB from {uid}: data_len={len(call.data or '')}")
