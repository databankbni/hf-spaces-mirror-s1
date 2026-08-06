---
title: MathVertex LaTeX API
emoji: 📐
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
---

# MathVertex LaTeX Formatter — Backend API

Flask backend for MathVertex's LaTeX Formatter tools. Deployed on
Hugging Face Spaces (Docker SDK, CPU Basic free tier).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sympy` | Algebraic expression string → LaTeX |
| POST | `/api/matrix` | 2D array + bracket type → LaTeX |
| POST | `/api/pandas` | Tabular data + style options → LaTeX table |
| POST | `/api/stargazer` | X, y arrays → OLS regression LaTeX table |
| POST | `/api/markdown` | Markdown text → LaTeX |
| POST | `/api/docx` | Uploaded `.docx` file → LaTeX |
| GET | `/api/health` | Liveness check |
| POST | `/api/factorize` | Integer → prime factorization + division steps |
| POST | `/api/totient` | Integer → φ(n) + prime factors + formula |
| POST | `/api/primitive-root` | Integer → primitive root + order-check table |
| POST | `/api/quad-residue` | a, p → Legendre symbol + Euler's criterion |
| POST | `/api/crt` | Remainders + moduli → Chinese Remainder Theorem solution |
| POST | `/api/rsa` | p, q, e (+ message/ciphertext) → keygen/encrypt/decrypt demonstrator |
| POST | `/api/miller-rabin` | Integer → primality + witness-by-witness steps |
| POST | `/api/integrate` | Expression → antiderivative + step-by-step rule breakdown |
| POST | `/api/limit` | Expression + point → limit value + indeterminate-form flag |
| POST | `/api/dsolve` | ODE (as `equation` [= `rhs`]) → solution + classification hints |
| POST | `/api/laplace` | Expression in t → Laplace transform in s |
| POST | `/api/series` | Expression + point + n → Taylor/Maclaurin series |
| POST | `/api/vector-calc` | gradient/divergence/curl → result |
| POST | `/api/euler-lagrange` | Lagrangian → Euler-Lagrange ODE |

## Quick test

```bash
curl -X POST https://cks03-mathhub-latex-api.hf.space/api/sympy \
  -H "Content-Type: application/json" \
  -d "{\"expression\": \"x**2 + 2*x + 1\"}"
```

Expected: `{"latex": "x^{2} + 2 x + 1"}`

## Notes

- Port is **7860** (Hugging Face's required port, not 8080).
- Regression uses plain `numpy`/`scipy.stats` (OLS via normal
  equations) rather than `statsmodels` — same statistics, lighter
  container, faster cold start.
- `/api/pandas` with `style: "pandas"` calls real
  `pandas.DataFrame.to_latex()`. `style: "r"` is a labelled
  approximation of xtable/kable conventions (`\hline`, not booktabs)
  since there's no R runtime in this container.
- `/api/markdown` and `/api/docx` call the `pandoc` binary directly
  via `subprocess` (installed at the OS level in the Dockerfile) —
  no `pypandoc` wrapper needed.
- CORS is already restricted to `https://YOUR-DOMAIN` plus VS Code Live
  Server's local-dev ports (`localhost:5500` / `127.0.0.1:5500`) — update
  `YOUR-DOMAIN` in `app.py` once the real domain is live.

## Security

- **Critical fix applied:** `sympy.sympify()` is not a sandbox.
  Verified directly in development — `sympify("__import__('os').system(...)")`
  actually executes it. Every confirmed exploit requires a literal
  `__` substring to reach Python's dunder attributes; `/api/sympy` and
  `/api/matrix` now validate input against a character allowlist, a
  dangerous-keyword blocklist, and a `__` block before it ever reaches
  `sympify()`, plus a 5-second SIGALRM timeout as defense-in-depth
  against algorithmic-complexity inputs. Verified against the
  confirmed exploits (now blocked) and all existing example
  expressions (still work).
- **Rate limiting** via `flask-limiter`, per-IP, tighter on the
  heavier endpoints (10/min for `/api/docx`, up to 30/min for
  `/api/sympy`). In-memory storage — resets on Space restart, which is
  fine at Phase 1 traffic levels.
- **CORS** restricted to the production domain plus local dev ports.
