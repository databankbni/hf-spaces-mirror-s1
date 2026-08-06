import asyncio
from dotenv import load_dotenv
from prisma import Prisma

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ Lỗi: Thiếu DATABASE_URL trong file .env")
    raise SystemExit(1)

client = Prisma()

async def run_cleanup():
    try:
        await client.connect()
        deleted_chapters = await client.chapter.delete_many()
        deleted_books = await client.book.delete_many()

        deleted_chapter_count = getattr(deleted_chapters, "count", deleted_chapters)
        deleted_book_count = getattr(deleted_books, "count", deleted_books)

        print(f"✅ Đã dọn dẹp chapters: Xóa {deleted_chapter_count} bản ghi.")
        print(f"✅ Đã dọn dẹp books: Xóa {deleted_book_count} bản ghi.")
        print("\n🚀 Xong! Hệ thống đã sẵn sàng để cào dữ liệu mới.")
    except Exception as e:
        print(f"❌ Có lỗi xảy ra: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_cleanup())
