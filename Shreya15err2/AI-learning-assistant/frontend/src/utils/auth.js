const BASE_URL = "/api";

// ── Token helpers ──────────────────────────────────────────────────────────
export function getToken() {
  return localStorage.getItem("ai_token");
}

export function getUsername() {
  return localStorage.getItem("ai_username");
}

export function isLoggedIn() {
  return !!getToken();
}

function saveSession(token, username) {
  localStorage.setItem("ai_token", token);
  localStorage.setItem("ai_username", username);
}

export function logout() {
  localStorage.removeItem("ai_token");
  localStorage.removeItem("ai_username");
}

// ── Auth API calls ─────────────────────────────────────────────────────────
async function authRequest(endpoint, body) {
  const res = await fetch(`${BASE_URL}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ detail: "Unknown error" }));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

export async function register(username, password) {
  const data = await authRequest("/auth/register", { username, password });
  saveSession(data.access_token, data.username);
  return data;
}

export async function login(username, password) {
  const data = await authRequest("/auth/login", { username, password });
  saveSession(data.access_token, data.username);
  return data;
}
