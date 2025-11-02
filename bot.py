import asyncio
from contextlib import suppress
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery)

from config import get_settings
from logging_conf import setup_logging
from db.base import init_db, Base
from db.repositories import UsersRepo, NotesRepo
from db.models import Note  # ← нужно для handle_note_selection
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
MAIN_KB.add(KeyboardButton("🗂️ Архив"))
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
@dp.message_handler(lambda m: (m.text or "").lower() in {"📂 архив", "архив"})
async def show_categories(message: types.Message):
    """
    Показывает список категорий с inline-кнопками.
    Каждая кнопка ведёт к заметкам этой категории.
    """
    await delete_last_reply(message.chat.id)
    
    if not notes_repo:
        sent = await message.answer("⚠️ Ошибка: БД недоступна")
        LAST_REPLY[message.chat.id] = sent.message_id
        return
    
    try:
        # Получаем все категории пользователя
        categories = await notes_repo.get_all_categories(message.from_user.id)
        
        if not categories:
            # Если заметок нет — показываем подсказку
            sent = await message.answer(
                "📂 У тебя пока нет заметок.\n\n"
                "Просто напиши текст (3-60 символов), и я сохраню его!"
            )
            LAST_REPLY[message.chat.id] = sent.message_id
            return
        
        # Создаём inline-клавиатуру
        keyboard = InlineKeyboardMarkup(row_width=1)  # по 1 кнопке в ряд
        
        for category, count in categories:
            # Добавляем кнопку для каждой категории
            keyboard.add(
                InlineKeyboardButton(
                    text=f"{category} ({count})",  # "🛒 Покупки (5)"
                    callback_data=f"cat_{category}"  # "cat_🛒 Покупки"
                )
            )
        
        sent = await message.answer(
            "📂 Твои категории:\n\n"
            "Выбери категорию, чтобы посмотреть заметки",
            reply_markup=keyboard  # ← кнопки прикрепляются к сообщению
        )
        
        LAST_REPLY[message.chat.id] = sent.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка при получении категорий: {e}", exc_info=True)
        await message.answer("❌ Ошибка. Попробуй ещё раз.")

   # Разобраться, если нужен блок ниже в данном исполнении

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

@dp.callback_query_handler(lambda c: c.data.startswith("cat_"))
async def handle_category_selection(callback: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку категории.
    Показывает список заметок выбранной категории.
    """
    # Извлекаем название категории из callback_data
    # Пример: "cat_🛒 Покупки" → "🛒 Покупки"
    category = callback.data[4:]  # убираем первые 4 символа ("cat_")
    
    if not notes_repo:
        await callback.answer("⚠️ Ошибка: БД недоступна", show_alert=True)
        return
    
    # Получаем заметки этой категории
    notes = await notes_repo.list_by_category(
        user_id=callback.from_user.id,
        category=category,
        limit=20  # можно больше, чем в старом "архиве"
    )
    
    if not notes:
        # Если в категории нет заметок (например, все удалены)
        await callback.answer("📭 В этой категории пока нет заметок", show_alert=True)
        return
    
    # Создаём клавиатуру с заметками
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for note in notes:
        # Обрезаем текст для кнопки (чтобы не было длинных кнопок)
        button_text = note.text[:35] + "..." if len(note.text) > 35 else note.text
        
        keyboard.add(
            InlineKeyboardButton(
                text=button_text,  # "купить молоко и хлеб"
                callback_data=f"note_{note.id}"  # "note_123"
            )
        )
    
    # Кнопка "Назад к категориям"
    keyboard.add(
        InlineKeyboardButton(
            "⬅️ Назад к категориям", 
            callback_data="back_to_categories"
        )
    )
    
    # Редактируем сообщение (вместо отправки нового)
    await callback.message.edit_text(
        f"📂 {category}\n\n"
        f"Заметок: {len(notes)}\n"
        "Выбери заметку для просмотра:",
        reply_markup=keyboard
    )
    
    # Убираем "часики" на кнопке
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("note_"))
async def handle_note_selection(callback: CallbackQuery):
    """
    Показывает детали выбранной заметки.
    """
    # Извлекаем ID заметки из callback_data
    # Пример: "note_123" → 123
    note_id = int(callback.data.split("_")[1])
    
    if not notes_repo:
        await callback.answer("⚠️ Ошибка: БД недоступна", show_alert=True)
        return
    
    # Получаем заметку из БД
    async with notes_repo.sm() as s:
        note = await s.get(Note, note_id)
        
        # Проверка безопасности: заметка существует и принадлежит пользователю
        if not note or note.user_id != callback.from_user.id:
            await callback.answer("❌ Заметка не найдена", show_alert=True)
            return
    
    # Формируем детали заметки
    details = (
        f"📝 <b>Заметка #{note.id}</b>\n\n"
        f"<b>Текст:</b> {note.text}\n"
        f"<b>Категория:</b> {note.category or '—'}\n"
        f"<b>Описание:</b> {note.description or '—'}\n"
        f"<b>Создана:</b> {note.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    )
    
    # Меню действий
    action_menu = InlineKeyboardMarkup(row_width=2)
    action_menu.add(
        InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{note.id}"),
        InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{note.id}")
    )
    # Возвращаемся к КАТЕГОРИИ (а не к списку всех категорий)
    action_menu.add(
        InlineKeyboardButton("⬅️ Назад", callback_data=f"cat_{note.category}")
    )
    
    await callback.message.edit_text(details, reply_markup=action_menu)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """
    Возвращает пользователя к списку категорий.
    """
    if not notes_repo:
        await callback.answer("⚠️ Ошибка: БД недоступна", show_alert=True)
        return
    
    # Получаем категории снова
    categories = await notes_repo.get_all_categories(callback.from_user.id)
    
    if not categories:
        await callback.message.edit_text("📂 У тебя пока нет заметок")
        await callback.answer()
        return
    
    # Создаём клавиатуру
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for category, count in categories:
        keyboard.add(
            InlineKeyboardButton(
                text=f"{category} ({count})",
                callback_data=f"cat_{category}"
            )
        )
    
    await callback.message.edit_text(
        "📂 Твои категории:\n\n"
        "Выбери категорию, чтобы посмотреть заметки",
        reply_markup=keyboard
    )
    
    await callback.answer()

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
        
    try:
        LAST_REPLY.pop(message.chat.id, None)

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