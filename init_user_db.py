import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from main import Base, DATABASE_URL  # yoki models.py dan import qiling

engine = create_async_engine(DATABASE_URL, echo=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(init_db())