// ═══════════════════════════════════════════════════════════════════════
//  COSMOCRAT — Hugging Face OAuth (PKCE flow, static space compatible)
//  Attivato quando lo Space ha `hf_oauth: true` nel front matter.
//  HF inietta window.huggingface.variables.OAUTH_CLIENT_ID automaticamente.
// ═══════════════════════════════════════════════════════════════════════

window.HFOAuth = (() => {
  const AUTHORIZE_URL = 'https://huggingface.co/oauth/authorize';
  const TOKEN_URL = 'https://huggingface.co/oauth/token';
  const USERINFO_URL = 'https://huggingface.co/oauth/userinfo';
  const PKCE_KEY = 'cosmocrat.oauth.pkce';
  const STATE_KEY = 'cosmocrat.oauth.state';
  const TOKEN_KEY = 'cosmocrat.oauth.token';
  const USER_KEY = 'cosmocrat.oauth.user';
  const SCOPES = 'openid profile inference-api';

  // Detect if we're running inside an HF Space with OAuth enabled
  function isAvailable() {
    return !!(window.huggingface &&
              window.huggingface.variables &&
              window.huggingface.variables.OAUTH_CLIENT_ID);
  }

  function getClientId() {
    return window.huggingface?.variables?.OAUTH_CLIENT_ID || null;
  }

  // Redirect URI: current page without query/hash
  function getRedirectUri() {
    const url = new URL(window.location.href);
    url.search = '';
    url.hash = '';
    return url.toString();
  }

  // Base64URL encoding for PKCE
  function base64UrlEncode(buffer) {
    const bytes = new Uint8Array(buffer);
    let str = '';
    for (const b of bytes) str += String.fromCharCode(b);
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  async function sha256(text) {
    const encoded = new TextEncoder().encode(text);
    return await crypto.subtle.digest('SHA-256', encoded);
  }

  function randomString(bytes = 32) {
    const arr = new Uint8Array(bytes);
    crypto.getRandomValues(arr);
    return base64UrlEncode(arr.buffer);
  }

  // Start OAuth flow — redirect user to HF authorize page
  async function login() {
    const clientId = getClientId();
    if (!clientId) throw new Error('HF OAuth non disponibile qui (Client ID mancante). Assicurati che lo Space abbia hf_oauth: true nel front matter YAML.');

    const codeVerifier = randomString(32);
    const codeChallenge = base64UrlEncode(await sha256(codeVerifier));
    const state = randomString(16);

    sessionStorage.setItem(PKCE_KEY, codeVerifier);
    sessionStorage.setItem(STATE_KEY, state);

    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: getRedirectUri(),
      response_type: 'code',
      scope: SCOPES,
      state,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    });
    window.location.href = `${AUTHORIZE_URL}?${params.toString()}`;
  }

  // Exchange authorization code for access token
  async function exchangeCode(code) {
    const clientId = getClientId();
    const codeVerifier = sessionStorage.getItem(PKCE_KEY);
    if (!clientId || !codeVerifier) throw new Error('Stato OAuth mancante');

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: clientId,
      code,
      redirect_uri: getRedirectUri(),
      code_verifier: codeVerifier,
    });

    const r = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    if (!r.ok) {
      const t = await r.text();
      throw new Error(`Token exchange fallito: ${r.status} — ${t.substring(0, 200)}`);
    }
    return await r.json();
  }

  // Fetch user info (for display purposes)
  async function fetchUserInfo(token) {
    const r = await fetch(USERINFO_URL, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!r.ok) return null;
    return await r.json();
  }

  // Handle redirect back from HF — call at page load
  // Returns { token, user } if we just came back from OAuth, else null.
  async function handleRedirect() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    if (!code) return null;

    // Cleanup URL immediately (remove query params from browser bar)
    const cleanUrl = getRedirectUri();
    window.history.replaceState({}, '', cleanUrl);

    // Verify state
    const expectedState = sessionStorage.getItem(STATE_KEY);
    if (!expectedState || state !== expectedState) {
      throw new Error('OAuth state non corrispondente (possibile CSRF)');
    }

    // Exchange code for token
    const tokenResp = await exchangeCode(code);
    const token = tokenResp.access_token;
    if (!token) throw new Error('Token non ricevuto');

    // Store token
    const expiresAt = Date.now() + ((tokenResp.expires_in || 28800) * 1000);
    localStorage.setItem(TOKEN_KEY, JSON.stringify({ token, expiresAt }));

    // Fetch user info
    let user = null;
    try {
      user = await fetchUserInfo(token);
      if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch(e) { /* non fatal */ }

    // Cleanup transient state
    sessionStorage.removeItem(PKCE_KEY);
    sessionStorage.removeItem(STATE_KEY);

    return { token, user, expiresAt };
  }

  // Retrieve stored token if still valid
  function getStoredToken() {
    try {
      const raw = localStorage.getItem(TOKEN_KEY);
      if (!raw) return null;
      const { token, expiresAt } = JSON.parse(raw);
      if (Date.now() > expiresAt - 60000) {  // 1min safety margin
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        return null;
      }
      return token;
    } catch { return null; }
  }

  function getStoredUser() {
    try {
      const raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(PKCE_KEY);
    sessionStorage.removeItem(STATE_KEY);
  }

  return {
    isAvailable,
    login,
    logout,
    handleRedirect,
    getStoredToken,
    getStoredUser,
    getClientId,
  };
})();
