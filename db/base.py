from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine
from sqlalchemy.orm import declarative_base

Base = declarative_base()
async_engine: AsyncEngine | None = None 
async_session: async_sessionmaker[AsyncSession] | None = None

async def init_db(db_url: str) -> async_sessionmaker[AsyncSession]:
    """
    Инициализирует асинхронный engine и sessionmaker.
    Устанавливает глобальные переменные async_engine и async_session.
    """
    global async_engine, async_session
    async_engine = create_async_engine(db_url, echo=False, future=True)
    async_session = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    return async_session

def get_async_engine() -> AsyncEngine | None:
    """
    Возвращает глобальный engine (после инициализации).
    Это помогает избежать проблем с None на старте.
    """
    return async_engine

def get_async_session() -> async_sessionmaker[AsyncSession] | None:
    """
    Возвращает глобальный sessionmaker.
    """
    return async_session