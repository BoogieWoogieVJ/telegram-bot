import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    bot_token: str
    db_url: str
    env: str
    openai_api_key: str

def _normalize_db_url(url: str) -> str:
    """
    Нормализует URL базы данных для работы с async SQLAlchemy.
    
    Почему это нужно:
    - Railway часто даёт URL вида postgres://...
    - Для async нужен postgresql+asyncpg://...
    - Если SQLite — оставляем sqlite+aiosqlite://...
    """
    # Шаг 1: postgres:// → postgresql://
    if url.startswith("postgres://"):
        url = "postgresql" + url[len("postgres"):]
    
    # Шаг 2: postgresql:// → postgresql+asyncpg://
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    
    return url

def get_settings() -> Settings:
    """
    Загружает настройки из переменных окружения.
    
    Приоритеты для DB_URL:
    1. DB_URL (если задан)
    2. DATABASE_URL (для Railway)
    3. sqlite+aiosqlite:///./notes.db (дефолт для локальной разработки)
    """
    token = os.getenv("BOT_TOKEN", "").strip()
    
    # Получаем raw URL из переменных окружения
    raw_db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./notes.db"
    
    # Нормализуем URL (добавляем asyncpg и т.д.)
    db_url = _normalize_db_url(raw_db_url)
    
    env = os.getenv("ENV", "dev").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

    # Валидация обязательных параметров
    if not token:
        raise RuntimeError("Отсутствует BOT_TOKEN в .env")
    
    if not openai_key:
        raise RuntimeError("Отсутствует OPENAI_API_KEY в .env")
    
    return Settings(
        bot_token=token,
        db_url=db_url,
        env=env,
        openai_api_key=openai_key
    )