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

def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./notes.db"
    db_url = db_url.strip()
#    db_url = os.getenv("DB_URL", "sqlite+aiosqlite:///./notes.db").strip()
    env = os.getenv("ENV", "dev").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()

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