"""
Worker Manager Service
Consumer process that pulls categories from Redis and executes them one by one.
Provides stability, reliability (RPOPLPUSH), and anti-ban pacing.
"""
import asyncio
import logging
import random
import signal
import gc
from datetime import datetime

from app.services.upstash_cache import get_upstash_cache
from app.services.news_processor import process_category
from app.utils.custom_logger import get_logger
from app.config import CATEGORIES

logger = get_logger(__name__)

class WorkerManager:
    def __init__(self):
        self.running = False
        # NOTE: Do NOT create a new NewsAggregator here.
        # We must use the process-wide singleton from scheduler.py so that
        # circuit breaker failure counts accumulate correctly across tasks.
        # A fresh NewsAggregator() resets all in-memory state and defeats
        # the circuit breaker pattern entirely.
        self._aggregator = None
        self.upstash = get_upstash_cache()
        self.pending_queue = "segmento:pending_news_queue"
        self.processing_queue = "segmento:processing_news_queue"
        self.dlq = "segmento:dead_letter_queue"
        self.visibility_map = "segmento:worker_visibility_tracker"
        self.visibility_timeout = 600  # 10 minutes

    @property
    def aggregator(self):
        """Lazy-load the shared aggregator singleton from scheduler."""
        if self._aggregator is None:
            from app.services.scheduler import _get_shared_aggregator
            self._aggregator = _get_shared_aggregator()
        return self._aggregator
        
    async def start(self):
        """Main consumer loop"""
        self.running = True
        self.polling_wait = 5  # Start with 5s polling wait
        logger.info("👷 [WORKER] Starting consumer loop...")
        
        # Initial jitter to stagger startup across multiple instances if they exist
        await asyncio.sleep(random.uniform(5, 15))
        
        while self.running:
            try:
                # 1. Atomic extraction (Pending -> Processing)
                # This ensures we don't lose the task if the worker crashes mid-run.
                category = await self.upstash.rpoplpush(self.pending_queue, self.processing_queue)
                
                if not category:
                    # 1b. Polite Polling: Exponential Backoff (5s -> 10s -> ... -> 60s)
                    self.polling_wait = min(self.polling_wait * 2, 60)
                    
                    # No new tasks, check for zombies occasionally (5% chance per empty loop)
                    if random.random() < 0.05:
                        await self.cleanup_zombie_tasks()
                    
                    logger.debug("📭 [WORKER] Queue empty. Polling backoff: %ds", self.polling_wait)
                    await asyncio.sleep(self.polling_wait)
                    continue
                
                # Reset polling wait when a task is found
                self.polling_wait = 5
                
                # 2. Track start time for visibility timeout
                start_time = int(datetime.now().timestamp())
                await self.upstash._execute_command(["HSET", self.visibility_map, category, start_time])

                # 3. Process the category
                logger.info("🎯 [WORKER] Processing task from queue: %s", category.upper())
                
                success = False
                try:
                    success = await process_category(category, self.aggregator)
                except Exception as proc_err:
                    logger.error("❌ [WORKER] Task failed: %s. Moving to DLQ.", category)
                    await self.upstash.lpush(self.dlq, f"{category} | {datetime.now().isoformat()} | {str(proc_err)}")
                finally:
                    # 4. Cleanup: Task ALWAYS removed from processing queue and visibility map
                    await self.upstash.lrem(self.processing_queue, 1, category)
                    await self.upstash._execute_command(["HDEL", self.visibility_map, category])
                    if success:
                        logger.info("✅ [WORKER] Task completed and cleaned: %s", category.upper())
                    else:
                        logger.warning("⚠️ [WORKER] Task cleaned from queue after failure: %s", category.upper())

                # 5. Mandatory inter-task spacing (HF-safe pacing)
                # Production logs show zero 429s from any free provider (Google RSS,
                # Medium, HackerNews all return 200). Inshorts fails with connection
                # reset (geo-block), not rate limit. No banning risk detected.
                #
                # Previous 30-90s was causing a 40+ minute full cycle time.
                # 8-18s provides enough jitter to avoid burst patterns while
                # keeping a full 22-category cycle under ~7 minutes.
                wait_time = random.uniform(8, 18)
                logger.info("💤 [WORKER] Pacing: sleeping for %.1fs...", wait_time)
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error("❌ [WORKER] Fatal error in consumer loop: %s", e)
                # Should we move to DLQ? In Task 5 we will implement the Reaper.
                await asyncio.sleep(30) # Backoff on error
            finally:
                # Explicit garbage collection per worker cycle (OOM Fix)
                gc.collect()

    def stop(self, *args):
        logger.info("👷 [WORKER] Stopping gracefully...")
        self.running = False

    async def cleanup_zombie_tasks(self):
        """
        The Reaper: Scans the processing queue for tasks that timed out.
        If a worker died while processing, this moves the task back to pending.
        """
        try:
            # 1. Get all tasks in processing queue
            processing_tasks = await self.upstash._execute_command(["LRANGE", self.processing_queue, 0, -1])
            if not processing_tasks:
                return

            # 2. Get start times from visibility map
            # Note: we use individual HGETs or HGETALL if safe
            current_time = int(datetime.now().timestamp())
            
            for category in processing_tasks:
                start_time_str = await self.upstash._execute_command(["HGET", self.visibility_map, category])
                if not start_time_str:
                    # Edge case: Task in processing but no timestamp? Move back to pending.
                    logger.warning("👻 [REAPER] Ghost task found for %s. Re-queueing.", category)
                    await self.upstash.lrem(self.processing_queue, 1, category)
                    await self.upstash.lpush(self.pending_queue, category)
                    continue
                
                start_time = int(start_time_str)
                if (current_time - start_time) > self.visibility_timeout:
                    # Task timed out!
                    logger.warning("🧟 [REAPER] Zombie task detected for %s (timed out). Recovering...", category)
                    await self.upstash.lrem(self.processing_queue, 1, category)
                    await self.upstash._execute_command(["HDEL", self.visibility_map, category])
                    await self.upstash.lpush(self.pending_queue, category)

        except Exception as reaper_err:
            logger.error("❌ [REAPER] Error: %s", reaper_err)

async def run_worker():
    """Main entry point for the worker process"""
    worker = WorkerManager()
    await worker.start()

if __name__ == "__main__":
    asyncio.run(run_worker())
