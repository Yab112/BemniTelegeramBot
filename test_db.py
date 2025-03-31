import asyncpg
import asyncio

DB_URL = "postgresql://postgres:nardi%40Me123%23@localhost:5432/Telegrambot"

async def test_db():
    try:
        conn = await asyncpg.connect(DB_URL)
        print("✅ Database connection successful!")
        await conn.close()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

asyncio.run(test_db())
