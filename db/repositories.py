from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User, Note


# ===============================
#   Класс для работы с users
# ===============================
class UsersRepo:
    """
    Репозиторий пользователей.
    Отвечает за создание пользователя в базе, если его ещё нет.
    """

    def __init__(self, sessionmaker):
        # sessionmaker — это фабрика асинхронных сессий (из base.py)
        self.sm = sessionmaker

    async def ensure(self, tg_id: int, username: str | None):
        """
        Проверяет, есть ли пользователь в базе. Если нет — создаёт.
        """
        async with self.sm() as s:  # открываем сессию
            u = await s.get(User, tg_id)  # ищем по id (primary key)
            if not u:
                s.add(User(id=tg_id, username=username))
                await s.commit()


# ===============================
#   Класс для работы с notes
# ===============================
class NotesRepo:
    """
    Репозиторий заметок.
    Отвечает за создание, чтение и выборку заметок.
    """

    def __init__(self, sessionmaker):
        self.sm = sessionmaker

    async def create(self, user_id: int, text: str, category: str | None = None, description: str | None = None):
        """
        Создаёт новую заметку для пользователя.
        
        Args:
            user_id: ID пользователя (Telegram ID)
            text: исходный текст заметки
            category: категория (определённая ИИ)
            description: описание от ИИ
        """
        async with self.sm() as s:
            note = Note(
                user_id=user_id,
                text=text,
                category=category,
                description=description,
                status="active",
            )
            s.add(note)
            await s.commit()
            await s.refresh(note)
            return note

    async def list_latest(self, user_id: int, limit: int = 20):
        """
        Возвращает последние N активных заметок пользователя.
        """
        async with self.sm() as s:
            query = (
                select(Note)
                .where(Note.user_id == user_id, Note.status == "active")
                .order_by(Note.created_at.desc())
                .limit(limit)
            )
            result = await s.execute(query)
            return result.scalars().all()

    # ← НОВЫЙ МЕТОД: получить заметки по категории
    async def list_by_category(self, user_id: int, category: str, limit: int = 20):
        """
        Возвращает заметки пользователя по определённой категории.
        
        Args:
            user_id: ID пользователя
            category: название категории (например "🛒 Покупки")
            limit: максимальное количество заметок
        """
        async with self.sm() as s:
            query = (
                select(Note)
                .where(
                    Note.user_id == user_id,
                    Note.category == category,
                    Note.status == "active"
                )
                .order_by(Note.created_at.desc())
                .limit(limit)
            )
            result = await s.execute(query)
            return result.scalars().all()

    # ← НОВЫЙ МЕТОД: получить все категории пользователя
    async def get_all_categories(self, user_id: int):
        """
        Возвращает все уникальные категории пользователя с количеством заметок.
        
        Returns:
            список кортежей (category, count)
            例: [("🛒 Покупки", 5), ("💡 Идеи", 2)]
        """
        async with self.sm() as s:
            query = (
                select(Note.category, func.count(Note.id).label("count"))
                .where(Note.user_id == user_id, Note.status == "active")
                .group_by(Note.category)
                .order_by(func.count(Note.id).desc())
            )
            result = await s.execute(query)
            return result.all()