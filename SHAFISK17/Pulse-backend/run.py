import uvicorn
import asyncio
import sys
import os

if __name__ == "__main__":
    # Force WindowsProactorEventLoopPolicy on Windows
    # This must be done before any asyncio loop is created
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # Run Uvicorn programmatically
    # DISABLE RELOAD to fix Windows Asyncio Subprocess issue
    # Playwright on Windows requires the main thread's event loop to be Proactor,
    # and Uvicorn's reloader messes this up.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        loop="asyncio",
        log_level="info"
    )
