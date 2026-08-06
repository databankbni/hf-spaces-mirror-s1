import { useState } from "react";
import { login, register } from "../utils/auth";

export default function LoginPage({ onSuccess }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(username, password);
      } else {
        await register(username, password);
      }
      onSuccess();
    } catch (err) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      {/* Animated background blobs */}
      <div className="login-blob login-blob-1" />
      <div className="login-blob login-blob-2" />
      <div className="login-blob login-blob-3" />

      <div className="login-card">
        {/* Logo / Header */}
        <div className="login-logo">
          <div className="login-logo-icon">🎓</div>
          <h1 className="login-title">AI Learning Assistant</h1>
          <p className="login-subtitle">Your smart study companion powered by AI</p>
        </div>

        {/* Tab switcher */}
        <div className="login-tabs">
          <button
            id="tab-login"
            className={`login-tab ${mode === "login" ? "active" : ""}`}
            onClick={() => { setMode("login"); setError(""); }}
          >
            Sign In
          </button>
          <button
            id="tab-register"
            className={`login-tab ${mode === "register" ? "active" : ""}`}
            onClick={() => { setMode("register"); setError(""); }}
          >
            Create Account
          </button>
          <div className={`login-tab-indicator ${mode === "register" ? "right" : ""}`} />
        </div>

        {/* Form */}
        <form className="login-form" onSubmit={handleSubmit} autoComplete="off">
          <div className="login-field">
            <label className="login-label" htmlFor="login-username">Username</label>
            <input
              id="login-username"
              className="login-input"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              autoFocus
            />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="login-password">Password</label>
            <input
              id="login-password"
              className="login-input"
              type="password"
              placeholder={mode === "register" ? "Min. 6 characters" : "Enter your password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 6 : 1}
            />
          </div>

          {error && (
            <div className="login-error">
              <span>⚠️</span> {error}
            </div>
          )}

          <button
            id="login-submit-btn"
            className="login-btn"
            type="submit"
            disabled={loading}
          >
            {loading ? (
              <span className="login-spinner" />
            ) : mode === "login" ? (
              "Sign In →"
            ) : (
              "Create Account →"
            )}
          </button>
        </form>

        <p className="login-footer">
          {mode === "login" ? (
            <>Don't have an account?{" "}
              <button className="login-link" onClick={() => { setMode("register"); setError(""); }}>
                Sign up free
              </button>
            </>
          ) : (
            <>Already have an account?{" "}
              <button className="login-link" onClick={() => { setMode("login"); setError(""); }}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
