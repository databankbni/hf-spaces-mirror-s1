// worker.js
var worker_default = {
  async fetch(request) {
    const url = new URL(request.url);
    const target = "https://gablilli-cartografo.hf.space";
    const targetUrl = target + url.pathname + url.search;
    const origin = request.headers.get("Origin");
    const allowedOriginRegex = /^https:\/\/([a-z0-9-]+\.)*insidegubbio\.com$/i;
    const isAllowedOrigin = origin && allowedOriginRegex.test(origin);
    if (request.method === "OPTIONS") {
      const headers = new Headers();
      if (isAllowedOrigin) {
        headers.set("Access-Control-Allow-Origin", origin);
        headers.set("Vary", "Origin");
      }
      headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS");
      headers.set(
        "Access-Control-Allow-Headers",
        request.headers.get("Access-Control-Request-Headers") || "Content-Type, Authorization"
      );
      headers.set("Access-Control-Max-Age", "86400");
      return new Response(null, { status: 204, headers });
    }
    const proxyRequest = new Request(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : void 0
    });
    const response = await fetch(proxyRequest);
    const newResponse = new Response(response.body, response);
    if (isAllowedOrigin) {
      newResponse.headers.set("Access-Control-Allow-Origin", origin);
      newResponse.headers.append("Vary", "Origin");
    }
    return newResponse;
  }
};
export {
  worker_default as default
};
