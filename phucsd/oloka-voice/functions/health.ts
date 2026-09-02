export const onRequest: PagesFunction = async (context) => {
  const url = new URL(context.request.url);
  
  // Construct the target URL for backend health check
  const targetUrl = `https://phucsd-oloka-voice.hf.space/health${url.search}`;
  
  // Clone request headers
  const headers = new Headers(context.request.headers);
  
  const proxyRequest = new Request(targetUrl, {
    method: context.request.method,
    headers: headers,
    body: context.request.method !== 'GET' && context.request.method !== 'HEAD' ? context.request.body : null,
    redirect: "follow",
  });
  
  try {
    const response = await fetch(proxyRequest);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } catch (error: any) {
    return new Response(JSON.stringify({
      detail: `Cloudflare Pages Health Proxy Error: ${error.message}`
    }), {
      status: 502,
      headers: { "Content-Type": "application/json" }
    });
  }
};
