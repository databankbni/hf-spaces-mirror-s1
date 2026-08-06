import os
import logging
import ssl
import asyncio
from fastapi import FastAPI, Request, Response
import uvicorn
from fastapi.responses import JSONResponse

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='[PROD] %(asctime)s - %(levelname)s - %(message)s')
logging.info("=== КОРНЕВОЙ СТАРТ ПРИЛОЖЕНИЯ ===")

ssl._create_default_https_context = ssl._create_unverified_context

# 1. Мгновенная инициализация FastAPI-приложения
app = FastAPI()

@app.get("/")
@app.get("/health")
async def health_check():
    """Эндпоинт для проверки работоспособности сервиса и БД."""
    is_db_alive = await db.ping()
    
    if not is_db_alive:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "info": "FastAPI Monolith Degraded",
                "db": "disconnected"
            }
        )
    
    return {
        "status": "ok",
        "info": "FastAPI Monolith Live",
        "db": "connected"
    }

@app.get("/webhook")
async def webhook_get():
    return {"status": "ready"}

# Глобальные объекты объявляем пустыми, чтобы не ломать импорт
bot = None
dp = None
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "") + WEBHOOK_PATH

def get_live_bot():
    global bot
    if bot is None:
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer
        
        logging.info("🔌 [Лениво] Создание объекта Bot в живом контексте вебхука...")
        proxy_url = "https://portfoliobot.pages.dev"
        custom_server = TelegramAPIServer(
            base=f"{proxy_url}/bot{{token}}/{{method}}",
            file=f"{proxy_url}/file/bot{{token}}/{{path}}",
            is_local=False
        )
        session = AiohttpSession(api=custom_server)
        bot = Bot(token=os.getenv("BOT_TOKEN"), session=session)
    return bot

try:
    logging.info("⏳ Импорт handlers и db...")
    import handlers
    import db
    from aiogram import Dispatcher, types
    from aiogram.fsm.storage.memory import MemoryStorage

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request):
        try:
            live_bot = get_live_bot()
            update_data = await request.json()
        except Exception as e:
            logging.error(f"Ошибка чтения апдейта вебхука: {e}")
            return Response(status_code=200)
        asyncio.create_task(_process_update_safely(live_bot, update_data))
        return Response(status_code=200)

    async def _process_update_safely(live_bot, update_data):
        try:
            await dp.feed_webhook_update(live_bot, update_data)
        except Exception as e:
            logging.error(f"Ошибка вебхука: {e}")

    # 2. Асинхронная фоновая инициализация сети (вебхуков и баз)
    @app.on_event("startup")
    async def startup_event():
        logging.info("🚀 [FastAPI] Запуск фоновой инициализации бота...")
        
        if not os.getenv("MONGO_URL") and os.getenv("MONGO_URI"):
            os.environ["MONGO_URL"] = os.getenv("MONGO_URI")

        # ИЗОЛИРОВАННЫЙ ЗАПУСК СЕТЕВОЙ ЛОГИКИ
        async def init_bot_network_and_db():
            try:
                # Инициализируем бота в контексте loop
                live_bot = get_live_bot()
                
                logging.info(f"⏳ [Параллельно] Регистрация вебхука в Telegram на {WEBHOOK_URL}...")
                await live_bot.set_webhook(WEBHOOK_URL, max_connections=40)
                logging.info(f"✅ [Параллельно] Вебхук успешно установлен на: {WEBHOOK_URL}")
                
                logging.info("🔄 [Параллельно] Запуск фонового воркера задач...")
                asyncio.create_task(handlers.main_queue_worker(live_bot))
                
                logging.info("🎉 БОТ ПОЛНОСТЬЮ ГОТОВ К ПРИЕМУ СООБЩЕНИЙ!")
                
                logging.info("⏳ [Параллельно] Попытка инициализации индексов БД...")
                try:
                    async with asyncio.timeout(5.0):
                        await db.init_indexes()
                    logging.info("✅ [Параллельно] Индексы БД успешно проверены!")
                except asyncio.TimeoutError:
                    logging.error("⚠️ [Предупреждение] MongoDB не ответила за 5 секунд.")
                except Exception as db_err:
                    logging.error(f"⚠️ [Предупреждение] Ошибка при проверке индексов БД: {db_err}")

            except Exception as e:
                logging.critical(f"❌ Критическая ошибка в параллельном старте: {e}", exc_info=True)

        asyncio.create_task(init_bot_network_and_db())
        logging.info("🟢 Фоновая задача инициализации успешно запланирована.")

except Exception as main_err:
    logging.critical(f"💥 КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА: {main_err}", exc_info=True)

# 3. ГЛОБАЛЬНЫЙ ЗАПУСК UVICORN (БЕЗ IF __NAME__)
PORT = int(os.getenv("PORT", 7860))
logging.info(f"🔥 Принудительный глобальный запуск Uvicorn на порту {PORT}...")
uvicorn.run(app, host="0.0.0.0", port=PORT)