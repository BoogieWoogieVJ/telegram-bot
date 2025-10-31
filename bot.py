import asyncio
from contextlib import suppress
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,)

from config import get_settings
from logging_conf import setup_logging
from db.base import init_db, Base
from db.repositories import UsersRepo, NotesRepo
from middlewares.traffic import TrafficLogMiddleware
from middlewares.auto_delete import AutoDeleteCommandsMiddleware
from ai_service import init_openai, analyze_note  # ← НОВОЕ

settings = get_settings()
logger = setup_logging(settings.env)

LAST_REPLY: Dict[int, int] = {}

# Глобальные экземпляры репозиториев (инициализируются в on_startup)
users_repo: Optional[UsersRepo] = None
notes_repo: Optional[NotesRepo] = None

async def delete_last_reply(chat_id: int) -> None:
    msg_id: Optional[int] = LAST_REPLY.get(chat_id)
    if msg_id:
        with suppress(Exception):
            await bot.delete_message(chat_id, msg_id)
        LAST_REPLY.pop(chat_id, None)

def _norm(text: str) -> str:
    # нормализуем текст кнопки: нижний регистр + без лишних пробелов
    return (text or "").strip().casefold()

bot = Bot(token=settings.bot_token, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

dp.middleware.setup(TrafficLogMiddleware(
    log_payload=(settings.env == "dev")
))
dp.middleware.setup(AutoDeleteCommandsMiddleware())

# меню
MAIN_KB = ReplyKeyboardMarkup(resize_keyboard=True)
MAIN_KB.add(KeyboardButton("📦 Архив"), KeyboardButton("🗂️ Категории"))
MAIN_KB.add(KeyboardButton("❓ Помощь"))


# ===== STARTUP / SHUTDOWN HANDLERS =====

async def on_startup(dispatcher):
    """
    Инициализация БД и создание таблиц при запуске бота.
    """
    global users_repo, notes_repo
    
    logger.info("🚀 Запуск бота...")
    logger.info(f"📝 Подключение к БД: {settings.db_url}")
    
    try:
        # ← НОВОЕ: Инициализируем OpenAI API
        init_openai(settings.openai_api_key)
        logger.info("✅ OpenAI API инициализирован")
        
        # Инициализируем БД (создаём engine и sessionmaker)
        # init_db устанавливает глобальные переменные async_engine и async_session
        async_session_maker = await init_db(settings.db_url)
        logger.info("✅ Engine и SessionMaker инициализированы")
        
        # Импортируем engine из db.base (он был установлен в init_db)
        from db.base import async_engine as engine
        if engine is None:
            raise RuntimeError("❌ Engine не инициализирован после init_db()")
        
        # Создаём все таблицы (если их ещё нет)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Таблицы созданы / уже существуют")
        
        # Создаём экземпляры репозиториев
        users_repo = UsersRepo(async_session_maker)
        notes_repo = NotesRepo(async_session_maker)
        logger.info("✅ Репозитории инициализированы")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации БД: {e}", exc_info=True)
        raise


async def on_shutdown(dispatcher):
    """
    Закрытие соединения с БД при остановке бота.
    """
    logger.info("🛑 Остановка бота...")
    try:
        from db.base import async_engine as engine
        if engine:
            await engine.dispose()
            logger.info("✅ БД отключена")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при отключении БД: {e}")


# ===== HANDLERS =====

@dp.message_handler(commands=["start"])
async def on_start(message: types.Message):
    # Добавляем пользователя в БД (если его ещё нет)
    if users_repo:
        await users_repo.ensure(message.from_user.id, message.from_user.username)
        logger.info(f"👤 Пользователь {message.from_user.id} (@{message.from_user.username}) начал работу с ботом")
    
    await message.answer(
        "\u2060",
        reply_markup=MAIN_KB
    )


@dp.message_handler(lambda m: (m.text or "").lower() in {"📦 архив", "архив"})
async def show_archive(message: types.Message):
    await delete_last_reply(message.chat.id)
    
    # Получаем заметки пользователя из БД
    if notes_repo:
        user_notes = await notes_repo.list_latest(message.from_user.id, limit=10)
        if user_notes:
            notes_text = "\n".join([f"• {note.text}" for note in user_notes])
            sent = await message.answer(f"📦 Ваши заметки:\n\n{notes_text}")
        else:
            sent = await message.answer("📦 Здесь будут храниться заметки, а пока тут пусто")
    else:
        sent = await message.answer("⚠️ Ошибка: БД недоступна")
    
    LAST_REPLY[message.chat.id] = sent.message_id


@dp.message_handler(lambda m: (m.text or "").lower() in {"❓ помощь", "помощь"})
async def show_help(message: types.Message):
    await delete_last_reply(message.chat.id)
    sent = await message.answer(
        "ℹ️ Раздел помощи.\n"
        "Для сохранения заметки просто напиши ее в чат (3-60 символов)\n"
        "Я автоматически ее проанализирую,\n"
        "добавлю больше информации к ней и\n"
        "присвою ей категорию.\n"
        "Позже ты можешь добавить контекст и сказать мне дополнить информацию"
    )
    LAST_REPLY[message.chat.id] = sent.message_id


# ← НОВОЕ: Хендлер для просмотра категорий
@dp.message_handler(lambda m: (m.text or "").lower() in {"🗂️ категории", "категории"})
async def show_categories(message: types.Message):
    """
    Показывает все категории пользователя с количеством заметок.
    """
    await delete_last_reply(message.chat.id)
    
    if not notes_repo:
        await message.reply("⚠️ Ошибка: БД недоступна")
        return
    
    try:
        categories = await notes_repo.get_all_categories(message.from_user.id)
        
        if not categories:
            sent = await message.reply("📂 У тебя пока нет заметок")
        else:
            text = "📂 Твои категории:\n\n"
            for category, count in categories:
                text += f"{category} (<b>{count}</b>)\n"
            
            sent = await message.reply(text)
        
        LAST_REPLY[message.chat.id] = sent.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка при получении категорий: {e}", exc_info=True)
        await message.reply("❌ Ошибка. Попробуй ещё раз.")


@dp.message_handler(content_types=[types.ContentType.TEXT])
async def handle_note(message: types.Message):
    """
    Обработка текстовых сообщений — сохранение заметок в БД с ИИ-анализом.
    """
    text = (message.text or "").strip()
    
    # Проверяем длину заметки (3-60 символов)
    if len(text) < 3 or len(text) > 60:
        await message.reply(
            "❌ Заметка должна быть от 3 до 60 символов. Попробуй ещё раз!"
        )
        return
    
        await delete_last_reply(message.chat.id)
    
    try:
        if notes_repo and users_repo:
            # Убеждаемся, что пользователь в БД
            await users_repo.ensure(message.from_user.id, message.from_user.username)
            
            # ← НОВОЕ: Показываем статус анализа
            status_msg = await message.reply("⏳ Анализ...")
            
            # ← НОВОЕ: Получаем существующие категории пользователя
            existing_categories = await notes_repo.get_all_categories(message.from_user.id)
            user_categories = [cat for cat, _ in existing_categories] if existing_categories else []
            # ← НОВОЕ: фильтруем None
            user_categories = [cat for cat in user_categories if cat is not None]
            
            # ← НОВОЕ: Анализируем текст через ИИ
            ai_result = await analyze_note(text, user_categories)
            category = ai_result.get("category", "🎯 Прочее")
            description = ai_result.get("description", "")
            
            # Создаём заметку
            note = await notes_repo.create(
                user_id=message.from_user.id,
                text=text,
                category=category,
                description=description
            )
            
            # ← НОВОЕ: Удаляем статус-сообщение
            with suppress(Exception):
                await bot.delete_message(message.chat.id, status_msg.message_id)
            
            logger.info(f"💾 Заметка #{note.id} создана: {text} → {category}")
            
            # ← НОВОЕ: Красивый ответ с информацией от ИИ
            await message.reply(
                f"✅ Заметка сохранена! 📝\n\n"
                f"<b>Текст:</b> {text}\n"
                f"<b>Категория:</b> {category}\n"
                f"<b>Описание:</b> {description}\n\n"
            )
            
        else:
            await message.reply("⚠️ Ошибка: БД недоступна")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении заметки: {e}", exc_info=True)
        await message.reply("❌ Ошибка при сохранении заметки. Попробуй ещё раз позже.")


# ===== MAIN =====

if __name__ == "__main__":
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )