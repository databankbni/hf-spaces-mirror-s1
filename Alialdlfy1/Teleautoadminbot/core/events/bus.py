class EventBus:
    def __init__(self): self._handlers={}
    def on(self,event,handler): self._handlers.setdefault(event,[]).append(handler)
    async def emit(self,event,**payload):
        for h in list(self._handlers.get(event,[])):
            result=h(**payload)
            if hasattr(result,'__await__'): await result
