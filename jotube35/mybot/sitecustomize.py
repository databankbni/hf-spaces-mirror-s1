import os
PROXY = 'proxy.hosty.qzz.io'

try:
    import requests.sessions
    orig_req = requests.sessions.Session.request
    def new_req(self, method, url, *args, **kwargs):
        if url and 'discord.com' in str(url): url = str(url).replace('discord.com', PROXY).replace('app.discord.com', PROXY)
        return orig_req(self, method, url, *args, **kwargs)
    requests.sessions.Session.request = new_req
except: pass

try:
    import aiohttp.client
    orig_aio = aiohttp.client.ClientSession._request
    async def new_aio(self, method, url, *args, **kwargs):
        if url and 'discord.com' in str(url): url = str(url).replace('discord.com', PROXY).replace('app.discord.com', PROXY)
        return await orig_aio(self, method, url, *args, **kwargs)
    aiohttp.client.ClientSession._request = new_aio
except: pass

try:
    import tls_client
    import requests
    class FakeTLSResponse:
        def __init__(self, res):
            self.status_code = res.status_code
            self.text = res.text
            self.content = res.content
            self.headers = res.headers
            self.url = res.url
        def json(self):
            import json
            return json.loads(self.text)

    class FakeTLSSession:
        def __init__(self, *args, **kwargs):
            self.session = requests.Session()
            self.proxies = {}
        def get(self, url, **kwargs): return self.execute_request("GET", url, **kwargs)
        def post(self, url, **kwargs): return self.execute_request("POST", url, **kwargs)
        def put(self, url, **kwargs): return self.execute_request("PUT", url, **kwargs)
        def patch(self, url, **kwargs): return self.execute_request("PATCH", url, **kwargs)
        def delete(self, url, **kwargs): return self.execute_request("DELETE", url, **kwargs)
        def execute_request(self, method, url, **kwargs):
            if url and 'discord.com' in str(url):
                url = str(url).replace('discord.com', PROXY).replace('app.discord.com', PROXY)
            for k in ['insecure_skip_verify', 'allow_redirects', 'certificate_pinning', 'client_identifier', 'random_tls_extension_order']:
                kwargs.pop(k, None)
            res = self.session.request(method, url, **kwargs)
            return FakeTLSResponse(res)

    tls_client.Session = FakeTLSSession
except: pass
