import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, Playwright, BrowserContext
import random
import sys

# Critical Fix for Windows: Force ProactorEventLoop for subprocess support
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Configure logging
logger = logging.getLogger(__name__)

# List of realistic User-Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
]

class BrowserManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BrowserManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        # Limit concurrent scraping operations to prevent OOM
        # 3 concurrent tabs is a safe starting point for a typical container (1-2GB RAM)
        self.semaphore = asyncio.Semaphore(3) 
        self._initialized = True
        logger.info("BrowserManager initialized (Semaphore: 3)")

    async def start(self):
        """Initialize the global browser instance"""
        if self.browser:
            return

        try:
            logger.info("Starting Playwright...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                # Add arguments to improve stability in container environments
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage', # Overcome limited /dev/shm size
                    '--disable-gpu', # Not needed for headless
                    '--single-process' # Required for memory compliance
                ]
            )
            logger.info("Global Browser Instance Started successfully")
        except Exception as e:
            logger.error(f"Failed to start Playwright: {e}")
            raise

    async def shutdown(self):
        """Gracefully close the global browser instance"""
        logger.info("Shutting down BrowserManager...")
        if self.browser:
            await self.browser.close()
            self.browser = None
        
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
            
        logger.info("BrowserManager shutdown complete")

    async def get_content(self, url: str) -> Optional[str]:
        """
        Fetch dynamic content using a fresh context from the shared browser.
        Controlled by semaphore to prevention resource exhaustion.
        """
        if not self.browser:
            logger.error("Browser not initialized! Call start() first.")
            return None

        async with self.semaphore:
            context: Optional[BrowserContext] = None
            page = None
            try:
                # Create a lightweight context (incognito-like)
                # Randomize user agent for basic anti-bot evasion
                context = await self.browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={'width': 1920, 'height': 1080},
                    java_script_enabled=True
                )
                
                page = await context.new_page()
                
                logger.info(f"Navigating to {url}")
                # "domcontentloaded" is faster than "networkidle" and usually sufficient for text
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
                # Wait a bit for JS hydration (React/Next.js)
                await page.wait_for_timeout(2000)
                
                content = await page.content()
                logger.info(f"Successfully scraped {len(content)} bytes from {url}")
                return content
                
            except Exception as e:
                logger.error(f"Scraping failed for {url}: {e}")
                return None
                
            finally:
                # CRITICAL: Always close context to free memory
                if page:
                    try:
                        await page.close()
                    except:
                        pass
                        
                if context:
                    try:
                        await context.close()
                    except:
                        pass

# Global Singleton Instance
browser_manager = BrowserManager()
