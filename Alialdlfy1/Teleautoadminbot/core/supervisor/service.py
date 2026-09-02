"""Crash isolation: each long-running service can be restarted independently."""
import asyncio, logging
log=logging.getLogger(__name__)

class Supervisor:
    def __init__(self, max_restarts=10): self.max_restarts=max_restarts; self._counts={}
    async def run(self, name, factory):
        while self._counts.get(name,0) < self.max_restarts:
            try:
                await factory()
                return
            except asyncio.CancelledError: raise
            except Exception:
                self._counts[name]=self._counts.get(name,0)+1
                log.exception("service %s crashed; restart %s/%s", name, self._counts[name], self.max_restarts)
                await asyncio.sleep(min(60, 2 ** min(self._counts[name], 6)))
        log.critical("service %s exceeded restart budget", name)
