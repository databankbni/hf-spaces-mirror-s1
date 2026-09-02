"""Provider failover policy. Provider adapters can be registered dynamically."""
class ProviderRouter:
    def __init__(self): self._providers=[]
    def register(self,name,client,priority=100): self._providers.append((priority,name,client)); self._providers.sort(key=lambda x:x[0])
    async def call(self, method, *args, **kwargs):
        errors=[]
        for _,name,client in self._providers:
            try: return await getattr(client,method)(*args,**kwargs)
            except Exception as exc: errors.append((name,exc))
        raise RuntimeError(f'All providers failed: {errors!r}')
