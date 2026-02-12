from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings import settings


def _async_url(url: str) -> str:
    """Convert sync DB URL to async driver URL.

    postgresql+psycopg://...  -> unchanged (psycopg3 supports async natively)
    sqlite+pysqlite://...     -> sqlite+aiosqlite://...
    """
    if url.startswith("sqlite+pysqlite"):
        return url.replace("sqlite+pysqlite", "sqlite+aiosqlite", 1)
    return url


def get_async_engine(url: str | None = None):
    effective_url = _async_url(url or settings.DATABASE_URL)
    return create_async_engine(effective_url, pool_pre_ping=True)


async_engine = get_async_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
