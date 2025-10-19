# db/models.py

# --- импорты из SQLAlchemy ---
from sqlalchemy import (
    Column,               # базовый класс для столбцов
    Integer,              # тип INTEGER
    BigInteger,           # большой целочисленный тип (для Telegram user_id)
    String,               # строка фикс/переменной длины
    Text,                 # длинный текст
    DateTime,             # тип даты/времени
    ForeignKey,           # внешний ключ
    func,                 # SQL-функции (например, NOW())
    Index,                # определение индексов
)
from sqlalchemy.orm import relationship  # связь между таблицами (ORM-отношения)

# --- наш общий Base из db/base.py ---
from .base import Base


# =========================
#   Таблица users
# =========================
class User(Base):
    __tablename__ = "users"                 # имя таблицы в БД

    # Telegram user_id. Он уже int и достаточно большой → BigInteger.
    id = Column(BigInteger, primary_key=True)

    # username необязателен (может быть None), поэтому nullable=True по умолчанию.
    username = Column(String(255))

    # когда запись создана. server_default=func.now() — время выставляет сама БД.
    created_at = Column(DateTime, server_default=func.now())


# =========================
#   Таблица notes
# =========================
class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)

    # владелец заметки
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Исходный текст заметки (ровно как ввёл пользователь)
    text = Column(Text, nullable=False)

    # ← НОВОЕ ПОЛЕ: категория, определённая ИИ (например: "🛒 Покупки")
    category = Column(String(100), nullable=True, default=None)

    # Описание от ИИ: контекст, пояснения, дополнения, рекомендации
    description = Column(Text, nullable=True)

    # статус заметки: "active" или "archived"
    status = Column(String(20), nullable=False, default="active")

    # время создания (ставит БД)
    created_at = Column(DateTime, server_default=func.now())

    # ORM-связь к User
    user = relationship("User")


# =========================
#   Индексы
# =========================

# Частый запрос: "дай последние заметки пользователя".
# Составной индекс по (user_id, created_at DESC) ускорит сортировку/фильтрацию.
Index("ix_notes_user_created", Note.user_id, Note.created_at.desc())

# ← НОВОЕ: поиск по категориям
Index("ix_notes_category", Note.user_id, Note.category)