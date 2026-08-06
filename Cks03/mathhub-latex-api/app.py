"""
MathVertex LaTeX Formatter — Flask backend
Deploy target: Hugging Face Spaces, Docker SDK, CPU Basic (free tier).
Every conversion function below was tested directly (outside Flask,
since Flask itself isn't installed in the dev sandbox) against known
correct outputs before being wrapped in a route. See the test notes
inline.

Endpoints:
  POST /api/sympy      — algebraic expression string -> LaTeX
  POST /api/matrix     — 2D array + bracket type     -> LaTeX
  POST /api/pandas     — tabular data + style options -> LaTeX table
  POST /api/stargazer  — X, y arrays                  -> OLS regression LaTeX table
  POST /api/markdown   — markdown text                -> LaTeX
  POST /api/docx       — uploaded .docx file           -> LaTeX
  GET  /api/health     — liveness check
"""
import os
import re
import signal
import subprocess
import tempfile
import traceback

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import sympy
from sympy.calculus.accumulationbounds import AccumBounds
import numpy as np
from scipy import stats

app = Flask(__name__)
# Global cap on request body size — defense in depth. Individual endpoints
# truncate strings to their own limits (MAX_EXPR_LEN etc.), but that
# truncation happens *after* Flask has already received and buffered the
# full body; without this, a single oversized request could still consume
# a lot of memory before any endpoint code runs. 10MB comfortably covers
# the largest legitimate payload (the 8MB docx upload) with headroom.
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
# Restricted to the production domain plus VS Code Live Server's default
# local-dev ports (5500/127.0.0.1:5500). Update YOUR-DOMAIN once the real
# domain is live.
CORS(app, origins=[
    "https://YOUR-DOMAIN",
    # Common local dev server ports — harmless to whitelist since these
    # only ever resolve to the developer's own machine, never a public
    # address. Add your exact port here if it's not one of these.
    "http://localhost:5500", "http://127.0.0.1:5500",   # VS Code Live Server
    "http://localhost:8080", "http://127.0.0.1:8080",   # http-server / live-server (npm)
    "http://localhost:3000", "http://127.0.0.1:3000",   # serve / Express default
    "http://localhost:5000", "http://127.0.0.1:5000",
    "http://localhost:8000", "http://127.0.0.1:8000",
])

# Per-IP rate limiting. In-memory storage is fine for a single free-tier
# instance (no Redis needed) — limits reset if the Space restarts, which
# is an acceptable tradeoff at Phase 1 traffic levels.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute", "1000 per day"],
    storage_uri="memory://",
)

MAX_MATRIX_DIM = 10
MAX_TABLE_ROWS = 500
MAX_REGRESSION_ROWS = 5000
MAX_TEXT_LEN = 200_000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8MB
MAX_EXPR_LEN = 500
MAX_EXPR_NEST_DEPTH = 15
SYMPY_TIMEOUT_SECONDS = 5


def err(msg, code=400):
    return jsonify({"error": msg}), code


# ── Expression-safety validator ─────────────────────────────────────
# CRITICAL: sympy.sympify() is NOT a sandbox. Verified directly in dev:
#   sympify("__import__('os').system('echo PWNED')")  ACTUALLY RUNS IT.
#   sympify("(1).__class__.__bases__[0].__subclasses__()")  walks the
#   full Python class tree — a classic sandbox-escape technique.
# Every confirmed exploit requires a literal "__" substring to reach
# dunder attributes; legitimate math expressions never need "__", so
# blocking it (plus a keyword blocklist and a strict character
# allowlist) neutralizes every attack found, while not breaking any
# real expression (Integral(...), Sum(...), sin(x), Symbol('x'), etc.
# all parse fine — verified against the existing example expressions).
_DANGEROUS_SUBSTRINGS = [
    '__', 'import', 'exec', 'eval', 'open(', 'os.', 'sys.', 'subprocess',
    'globals', 'locals', 'getattr', 'setattr', 'delattr', 'compile(',
    'input(', 'breakpoint', 'system', 'builtins', 'lambda', 'class ',
    'def ', '\\x', 'chr(',
]
_SAFE_EXPR_CHARS = re.compile(r"^[A-Za-z0-9\s\+\-\*\/\^\(\)\[\]\{\}\,\.\_\=\<\>\!\:\'\"]+$")


def validate_expr_safety(s):
    if not s or not s.strip():
        raise ValueError("Expression is empty")
    if len(s) > MAX_EXPR_LEN:
        raise ValueError(f"Expression too long (max {MAX_EXPR_LEN} characters)")
    low = s.lower()
    for bad in _DANGEROUS_SUBSTRINGS:
        if bad in low:
            raise ValueError(f"Expression contains a disallowed pattern ({bad!r})")
    if not _SAFE_EXPR_CHARS.match(s):
        raise ValueError("Expression contains a disallowed character")
    depth = 0
    max_depth = 0
    for ch in s:
        if ch in '([{':
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch in ')]}':
            depth -= 1
    if max_depth > MAX_EXPR_NEST_DEPTH:
        raise ValueError("Expression nesting is too deep")
    return True


class _TimeoutError(Exception):
    pass


def _raise_timeout(signum, frame):
    raise _TimeoutError("Computation took too long")


def sympify_with_timeout(expr_str, seconds=SYMPY_TIMEOUT_SECONDS):
    """Defense-in-depth against algorithmic-complexity DoS (e.g. deeply
    nested symbolic expansion). SIGALRM-based — Unix only, which is what
    the Docker container runs. Each gunicorn worker handles one request
    at a time, so this cleanly bounds worst-case time per request."""
    old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(seconds)
    try:
        validate_expr_safety(expr_str)
        expr = sympy.sympify(expr_str, evaluate=False)
        latex_str = sympy.latex(expr)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    return latex_str


# ── /api/sympy ──────────────────────────────────────────────────────
@app.route('/api/sympy', methods=['POST'])
@limiter.limit("30 per minute")
def api_sympy():
    data = request.get_json(silent=True)
    if not data or 'expression' not in data:
        return err("No expression provided")
    expr_str = str(data['expression'])[:MAX_EXPR_LEN]
    try:
        latex_str = sympify_with_timeout(expr_str)
        return jsonify({"latex": latex_str})
    except _TimeoutError:
        return err("Expression took too long to process — try something simpler", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Parse error: {e}")


# ── /api/matrix ──────────────────────────────────────────────────────
# Tested directly: sympy.latex(M, mat_str='bmatrix') double-wraps in
# \left[...\right] AROUND the bmatrix's own brackets — a real bug.
# Fix: render with mat_delim='' (no wrapper), strip the bare \begin{matrix}
# tags, then wrap with the literal requested environment ourselves.
_MAT_ENVS = {'bmatrix', 'pmatrix', 'vmatrix', 'Vmatrix', 'matrix'}


def matrix_to_latex(rows, bracket):
    if bracket not in _MAT_ENVS:
        bracket = 'bmatrix'
    n = len(rows)
    m = len(rows[0]) if n else 0
    if n == 0 or m == 0:
        raise ValueError("Matrix is empty")
    if n > MAX_MATRIX_DIM or m > MAX_MATRIX_DIM:
        raise ValueError(f"Matrix too large (max {MAX_MATRIX_DIM}x{MAX_MATRIX_DIM})")
    if any(len(r) != m for r in rows):
        raise ValueError("All rows must have the same length")
    old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(SYMPY_TIMEOUT_SECONDS)
    try:
        cells = []
        for row in rows:
            for c in row:
                cell_str = str(c)[:100]
                validate_expr_safety(cell_str)
                cells.append(cell_str)
        parsed = [[sympy.sympify(cells[i * m + j], evaluate=False) for j in range(m)] for i in range(n)]
        M = sympy.Matrix(parsed)
        body = sympy.latex(M, mat_str='matrix', mat_delim='')
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    inner = body.replace('\\begin{matrix}', '').replace('\\end{matrix}', '')
    return '\\begin{' + bracket + '}' + inner + '\\end{' + bracket + '}'


@app.route('/api/matrix', methods=['POST'])
@limiter.limit("30 per minute")
def api_matrix():
    data = request.get_json(silent=True)
    if not data or 'rows' not in data:
        return err("No matrix rows provided")
    try:
        latex_str = matrix_to_latex(data['rows'], data.get('bracket', 'bmatrix'))
        return jsonify({"latex": latex_str})
    except _TimeoutError:
        return err("Matrix took too long to process — try fewer/simpler entries", 408)
    except Exception as e:
        return err(f"Matrix error: {e}")


# ── /api/pandas ──────────────────────────────────────────────────────
# 'pandas' style uses REAL pandas.DataFrame.to_latex() — genuine
# booktabs output with correct LaTeX-escaping of special characters
# (verified directly: Col_A -> Col\_A, 50% -> 50\%, etc).
# 'r' style approximates xtable/kable conventions (\hline, not
# booktabs) — there's no R runtime in this container, so this is a
# labelled approximation, not real xtable output.
import pandas as pd


def df_table_to_latex(columns, rows, style='pandas', index=False,
                       caption=None, label=None, decimals=2, alignment=None):
    if len(rows) > MAX_TABLE_ROWS:
        raise ValueError(f"Too many rows (max {MAX_TABLE_ROWS})")
    if style == 'pandas':
        df = pd.DataFrame(rows, columns=columns)
        return df.to_latex(
            index=index,
            float_format=f"{{:.{decimals}f}}".format,
            column_format=alignment,
            caption=caption,
            label=label,
            escape=True,
        )
    # R/xtable-style approximation (hline borders, no booktabs)
    ncols = len(columns) + (1 if index else 0)
    align = alignment or ('l' + 'r' * (ncols - 1))

    def fmt(v):
        if isinstance(v, bool):
            return str(v)
        try:
            return f'{float(v):.{decimals}f}'
        except (TypeError, ValueError):
            return str(v)

    headers = ([''] if index else []) + [str(c) for c in columns]
    body_rows = [(([str(i)] if index else []) + [fmt(v) for v in row]) for i, row in enumerate(rows)]
    out = []
    wrap_table = bool(caption or label)
    if wrap_table:
        out += ['\\begin{table}[h]', '\\centering']
    out.append('\\begin{tabular}{' + align + '}')
    out.append('\\hline')
    out.append(' & '.join(headers) + ' \\\\')
    out.append('\\hline')
    for r in body_rows:
        out.append(' & '.join(r) + ' \\\\')
    out.append('\\hline')
    out.append('\\end{tabular}')
    if caption:
        out.append('\\caption{' + caption + '}')
    if label:
        out.append('\\label{' + label + '}')
    if wrap_table:
        out.append('\\end{table}')
    return '\n'.join(out)


@app.route('/api/pandas', methods=['POST'])
@limiter.limit("20 per minute")
def api_pandas():
    data = request.get_json(silent=True)
    if not data or 'columns' not in data or 'rows' not in data:
        return err("Provide 'columns' and 'rows'")
    try:
        latex_str = df_table_to_latex(
            data['columns'], data['rows'],
            style=data.get('style', 'pandas'),
            index=bool(data.get('index', False)),
            caption=data.get('caption'),
            label=data.get('label'),
            decimals=int(data.get('decimals', 2)),
            alignment=data.get('alignment'),
        )
        return jsonify({"latex": latex_str})
    except Exception as e:
        return err(f"Table error: {e}")


# ── /api/stargazer ──────────────────────────────────────────────────
# OLS via normal equations (X'X)^-1 X'y, exactly as a textbook
# derivation, no statsmodels dependency. Cross-checked against
# numpy.polyfit for a simple-regression case — matched to 4dp.
def ols_regression(X, y, var_names=None):
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    n, k = X.shape
    p = k + 1
    if n <= p:
        raise ValueError(f"Need more observations ({n}) than parameters ({p})")
    Xd = np.column_stack([np.ones(n), X])
    XtX = Xd.T @ Xd
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        raise ValueError("X'X is singular — predictors may be collinear")
    beta = XtX_inv @ Xd.T @ y
    resid = y - Xd @ beta
    rss = float(np.sum(resid ** 2))
    df_resid = n - p
    sigma2 = rss / df_resid
    se = np.sqrt(np.diag(sigma2 * XtX_inv))
    t_stats = beta / se
    p_values = 2 * stats.t.sf(np.abs(t_stats), df_resid)
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - rss / tss if tss > 0 else float('nan')
    adj_r2 = 1 - (1 - r2) * (n - 1) / (n - p)
    if p > 1 and rss > 0:
        f_stat = (tss - rss) / (p - 1) / (rss / df_resid)
        f_pvalue = stats.f.sf(f_stat, p - 1, df_resid)
    else:
        f_stat, f_pvalue = float('nan'), float('nan')
    names = ['Intercept'] + (var_names or [f'X{i+1}' for i in range(k)])
    return {
        'names': names, 'coef': beta.tolist(), 'se': se.tolist(),
        't': t_stats.tolist(), 'p': p_values.tolist(),
        'r2': r2, 'adj_r2': adj_r2, 'f_stat': f_stat, 'f_pvalue': f_pvalue,
        'n': n, 'df_resid': df_resid,
    }


def _stars(p):
    return '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.1 else ''


def stargazer_latex(res, dep_var='y', title='Regression Results'):
    L = []
    L += ['\\begin{table}[!htbp] \\centering',
          '  \\caption{' + title + '}',
          '  \\label{tab:regression}',
          '\\begin{tabular}{@{\\extracolsep{5pt}}lc}',
          '\\\\[-1.8ex]\\hline',
          '\\hline \\\\[-1.8ex]',
          ' & \\multicolumn{1}{c}{\\textit{Dependent variable:}} \\\\',
          '\\cline{2-2}',
          ' & \\multicolumn{1}{c}{' + dep_var + '} \\\\',
          '\\hline \\\\[-1.8ex]']
    intercept_i = res['names'].index('Intercept')
    for i, name in enumerate(res['names']):
        if name == 'Intercept':
            continue
        c, se, p = res['coef'][i], res['se'][i], res['p'][i]
        L.append(f' {name} & {c:.3f}{_stars(p)} \\\\')
        L.append(f'  & ({se:.3f}) \\\\')
    c, se, p = res['coef'][intercept_i], res['se'][intercept_i], res['p'][intercept_i]
    L.append(f' Constant & {c:.3f}{_stars(p)} \\\\')
    L.append(f'  & ({se:.3f}) \\\\')
    L.append('\\hline \\\\[-1.8ex]')
    L.append(f'Observations & {res["n"]} \\\\')
    L.append(f'R$^{{2}}$ & {res["r2"]:.3f} \\\\')
    L.append(f'Adjusted R$^{{2}}$ & {res["adj_r2"]:.3f} \\\\')
    if not np.isnan(res['f_stat']):
        L.append(f'F Statistic & {res["f_stat"]:.3f} \\\\')
    L += ['\\hline', '\\hline \\\\[-1.8ex]',
          '\\textit{Note:}  & \\multicolumn{1}{r}{$^{*}$p$<$0.1; $^{**}$p$<$0.05; $^{***}$p$<$0.01} \\\\',
          '\\end{tabular}', '\\end{table}']
    return '\n'.join(L)


@app.route('/api/stargazer', methods=['POST'])
@limiter.limit("15 per minute")
def api_stargazer():
    data = request.get_json(silent=True)
    if not data or 'X' not in data or 'y' not in data:
        return err("Provide 'X' (2D array) and 'y' (1D array)")
    try:
        X, y = data['X'], data['y']
        if len(X) > MAX_REGRESSION_ROWS:
            return err(f"Too many observations (max {MAX_REGRESSION_ROWS})")
        first_row_len = len(X[0]) if X and isinstance(X[0], list) else 1
        if first_row_len > 100:
            return err("Too many predictor variables (max 100)")
        res = ols_regression(X, y, data.get('var_names'))
        latex_str = stargazer_latex(
            res, dep_var=data.get('dep_var', 'y'),
            title=data.get('title', 'Regression Results'))
        return jsonify({"latex": latex_str, "stats": {
            k: res[k] for k in ('r2', 'adj_r2', 'f_stat', 'f_pvalue', 'n', 'df_resid')
        }})
    except Exception as e:
        return err(f"Regression error: {e}")


# ── /api/markdown ────────────────────────────────────────────────────
# Direct subprocess call to the pandoc binary — no pypandoc wrapper
# needed (pypandoc is itself just a subprocess wrapper). Verified
# directly against the pandoc CLI for headers/bold/italic/lists/
# tables/blockquotes/code blocks.
def run_pandoc(args, input_bytes=None, timeout=20):
    try:
        proc = subprocess.run(
            ['pandoc'] + args, input=input_bytes,
            capture_output=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("pandoc is not installed on the server")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Conversion timed out")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8', 'replace')[:1000])
    return proc.stdout.decode('utf-8', 'replace')


# ── Unicode math symbol -> safe LaTeX ───────────────────────────────
# When a source document has math symbols (∈, Σ, Δ, ...) typed as plain
# Unicode characters rather than as proper Word equation (OMML) objects,
# pandoc correctly treats them as literal text and emits them as raw
# UTF-8 in the .tex output — that's not a pandoc bug, it has no way to
# know they were meant as math. The problem shows up one step later:
# pandoc's own --standalone template only handles this raw Unicode
# correctly when compiled with XeLaTeX/LuaLaTeX (via unicode-math); under
# plain pdfLaTeX (still the most common default, e.g. in Overleaf and most
# local installs), these characters have no font mapping and are SILENTLY
# DROPPED during compilation — confirmed directly: compiled a real
# affected document with pdflatex and every ∈/Σ/Δ vanished with no error,
# while the identical content compiled clean once each symbol was
# rewritten as its LaTeX macro ($\in$, $\Delta$, ...).
# Fix: rewrite these to their macro form ourselves, wrapped in their own
# inline math mode ($...$) so they're self-contained and correct under
# ANY engine, rather than depending on the user picking XeLaTeX.
_SUBSCRIPT_CHARS = {
    'ₐ':'a','ᵦ':'b','ᵧ':'g','ᵢ':'i','ⱼ':'j','ₖ':'k','ₗ':'l','ₘ':'m','ₙ':'n',
    'ₒ':'o','ₚ':'p','ᵩ':'q','ᵣ':'r','ₛ':'s','ₜ':'t','ᵤ':'u','ᵥ':'v','ₓ':'x',
    '₀':'0','₁':'1','₂':'2','₃':'3','₄':'4','₅':'5','₆':'6','₇':'7','₈':'8','₉':'9',
}
# Dedicated operator glyphs AND the Greek letters people commonly type
# instead of them (e.g. Σ for ∑) — both map to the same LaTeX macro.
_BIG_OPS = {'∑': r'\sum', '∏': r'\prod', '∫': r'\int', 'Σ': r'\sum', 'Π': r'\prod'}
_UNICODE_MATH_MAP = {
    '∈': r'\in', '∉': r'\notin', '⊂': r'\subset', '⊆': r'\subseteq',
    '⊃': r'\supset', '⊇': r'\supseteq', '∪': r'\cup', '∩': r'\cap',
    '∅': r'\emptyset', '∀': r'\forall', '∃': r'\exists', '∄': r'\nexists',
    '≠': r'\neq', '≤': r'\leq', '≥': r'\geq', '≈': r'\approx', '≡': r'\equiv',
    '→': r'\to', '⇒': r'\Rightarrow', '⇔': r'\Leftrightarrow', '↔': r'\leftrightarrow',
    '∞': r'\infty', '±': r'\pm', '∓': r'\mp', '×': r'\times', '÷': r'\div',
    '∂': r'\partial', '∇': r'\nabla', '∏': r'\prod', '∫': r'\int',
    '∝': r'\propto', '∴': r'\therefore', '∵': r'\because',
    'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta', 'ε': r'\epsilon',
    'θ': r'\theta', 'λ': r'\lambda', 'μ': r'\mu', 'π': r'\pi', 'σ': r'\sigma',
    'φ': r'\phi', 'ω': r'\omega', 'Δ': r'\Delta', 'Ω': r'\Omega', 'Σ': r'\Sigma',
    'Φ': r'\Phi', 'Γ': r'\Gamma', 'Λ': r'\Lambda', 'Θ': r'\Theta', 'Π': r'\Pi',
}
_SUB_RUN = ''.join(_SUBSCRIPT_CHARS)
_BIGOP_CHARS = ''.join(_BIG_OPS)
_BIGOP_SUB_RE = re.compile(
    r'([' + _BIGOP_CHARS + r'])([' + _SUB_RUN + r']+)(∈([A-Za-z][A-Za-z0-9_]*))?'
)
def _bigop_sub_repl(m):
    op = _BIG_OPS[m.group(1)]
    sub = ''.join(_SUBSCRIPT_CHARS[c] for c in m.group(2))
    if m.group(4):
        return '$' + op + '_{' + sub + r' \in ' + m.group(4) + '}$'
    return '$' + op + '_{' + sub + '}$'
_UNICODE_MATH_RE = re.compile(
    '|'.join(re.escape(c) for c in sorted(_UNICODE_MATH_MAP, key=len, reverse=True))
)
def latexify_unicode_math(text):
    text = _BIGOP_SUB_RE.sub(_bigop_sub_repl, text)
    text = _UNICODE_MATH_RE.sub(lambda m: '$' + _UNICODE_MATH_MAP[m.group(0)] + '$', text)
    return text


@app.route('/api/markdown', methods=['POST'])
@limiter.limit("15 per minute")
def api_markdown():
    data = request.get_json(silent=True)
    if not data or 'markdown' not in data:
        return err("No markdown provided")
    md = str(data['markdown'])[:MAX_TEXT_LEN]
    standalone = bool(data.get('standalone', False))
    args = ['-f', 'markdown', '-t', 'latex']
    if standalone:
        args.append('--standalone')
    try:
        latex_str = run_pandoc(args, input_bytes=md.encode('utf-8'))
        latex_str = latexify_unicode_math(latex_str)
        return jsonify({"latex": latex_str})
    except RuntimeError as e:
        return err(str(e), 502)


# ── /api/docx ────────────────────────────────────────────────────────
# Multipart file upload -> temp file -> pandoc -> cleanup. Verified
# directly with a python-docx-generated test file containing headings,
# bold/italic runs, and a table — all converted correctly.
@app.route('/api/docx', methods=['POST'])
@limiter.limit("10 per minute")
def api_docx():
    if 'file' not in request.files:
        return err("No file uploaded")
    f = request.files['file']
    if not f.filename.lower().endswith('.docx'):
        return err("File must be a .docx")
    raw = f.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return err("File too large (max 8MB)")
    standalone = request.form.get('standalone', 'true').lower() != 'false'

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        args = ['-f', 'docx', '-t', 'latex', tmp_path]
        if standalone:
            args.append('--standalone')
        latex_str = run_pandoc(args)
        latex_str = latexify_unicode_math(latex_str)
        return jsonify({"latex": latex_str})
    except RuntimeError as e:
        return err(str(e), 502)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.route('/api/health', methods=['GET'])
@limiter.exempt
def api_health():
    return jsonify({"status": "ok"})


# ══════════════════════════════════════════════════════════════════
# CALCULUS & DIFFERENTIAL EQUATIONS
# Per the implementation matrix: SymPy for limits/ODEs/Laplace/series/
# vector calculus/Euler-Lagrange. The doc recommends Maxima for
# step-by-step integration — Maxima isn't installed in the dev sandbox
# (no network access to verify it), so /api/integrate uses SymPy's
# own manualintegrate engine instead, which DOES give real step-by-
# step rules (PartsRule, URule, ArctanRule, etc.) and was verified
# directly against 8 cases (power, parts, substitution, arctan, trig
# product, cyclic parts, sum rule, constant multiple) — every result
# differentiated back to confirm correctness. Swap to Maxima later if
# SymPy's manualintegrate hits a wall on a specific edge case.
#
# Every endpoint here parses a user-supplied expression string through
# sympify, so every one of them goes through the SAME validate_expr_
# safety() + SIGALRM timeout used by /api/sympy — this is exactly the
# class of input that the confirmed sympify RCE exploited.
# ══════════════════════════════════════════════════════════════════
from sympy import (Function, Derivative, Eq, dsolve as sympy_dsolve, laplace_transform,
                    limit as sympy_limit, oo, Symbol)
from sympy.calculus.euler import euler_equations
from sympy.integrals.manualintegrate import integral_steps, manualintegrate


def _safe_sympify(expr_str, local_syms=None):
    validate_expr_safety(expr_str)
    old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(SYMPY_TIMEOUT_SECONDS)
    try:
        return sympy.sympify(expr_str, locals=local_syms or {})
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _explain_integral_rule(rule):
    """Recursively flatten a manualintegrate Rule object into a list
    of human-readable step strings. Handles the common rule types;
    anything else gets a generic but honest fallback description
    rather than a wrong-looking explanation."""
    name = type(rule).__name__
    steps = []
    if name == 'PowerRule':
        steps.append(f"Power rule: \u222b{rule.base}^{rule.exp} dx = {rule.base}^({rule.exp}+1)/({rule.exp}+1)")
    elif name == 'ExpRule':
        steps.append(f"Exponential rule applied to {rule.base}^({rule.exp})")
    elif name == 'ReciprocalRule':
        steps.append(f"Reciprocal rule: \u222b1/{rule.base} dx = ln|{rule.base}|")
    elif name == 'ArctanRule':
        steps.append("Arctan rule: matches \u222b1/(a\u00b2x\u00b2+c) dx \u2192 arctan form")
    elif name == 'SinRule':
        steps.append("\u222bsin(x) dx = -cos(x)")
    elif name == 'CosRule':
        steps.append("\u222bcos(x) dx = sin(x)")
    elif name == 'ConstantRule':
        steps.append(f"Constant rule: \u222b{rule.integrand} dx = {rule.integrand}\u00b7x")
    elif name == 'ConstantTimesRule':
        steps.append(f"Constant multiple rule: factor out {rule.constant}")
        steps.extend(_explain_integral_rule(rule.substep))
    elif name == 'URule':
        steps.append(f"Substitution: let u = {rule.u_func}")
        steps.extend(_explain_integral_rule(rule.substep))
    elif name == 'PartsRule':
        steps.append(f"Integration by parts: u = {rule.u}, dv = {rule.dv} dx")
        steps.extend(_explain_integral_rule(rule.v_step))
        if rule.second_step is not None:
            steps.append("Then integrate the remaining term:")
            steps.extend(_explain_integral_rule(rule.second_step))
    elif name == 'CyclicPartsRule':
        steps.append("Cyclic integration by parts \u2014 the original integral reappears, solve algebraically")
        for pr in rule.parts_rules:
            steps.extend(_explain_integral_rule(pr))
    elif name == 'AddRule':
        steps.append("Split into a sum of integrals (linearity):")
        for sub in rule.substeps:
            steps.extend(_explain_integral_rule(sub))
    elif name == 'AlternativeRule':
        steps.extend(_explain_integral_rule(rule.alternatives[0]))
    else:
        steps.append(f"Apply the {name.replace('Rule','')} rule to {rule.integrand}")
    return steps


@app.route('/api/integrate', methods=['POST'])
@limiter.limit("20 per minute")
def api_integrate():
    data = request.get_json(silent=True)
    if not data or 'expression' not in data:
        return err("Provide 'expression'")
    try:
        var_name = str(data.get('variable', 'x'))[:5]
        if not re.match(r'^[A-Za-z]$', var_name):
            return err("variable must be a single letter")
        x = sympy.Symbol(var_name)
        expr = _safe_sympify(str(data['expression'])[:MAX_EXPR_LEN], {var_name: x})
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            rule = integral_steps(expr, x)
            result = manualintegrate(expr, x)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        steps = _explain_integral_rule(rule)
        return jsonify({
            "expression": sympy.latex(expr), "result": sympy.latex(result),
            "result_plain": str(result), "steps": steps,
        })
    except _TimeoutError:
        return err("Integration took too long \u2014 try a simpler expression", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Integration error: {e}")


def _classify_ratio(nv, dv):
    if nv == 0 and dv == 0: return '0/0'
    if nv in (sympy.oo, -sympy.oo) and dv in (sympy.oo, -sympy.oo): return '\\infty/\\infty'
    return None

def _is_simple_power(f, var):
    """True if f is just var**n for constant n -- has a clean reciprocal
    derivative, so it belongs as the denominator in a 0*inf rewrite."""
    if f == var:
        return True
    if isinstance(f, sympy.Pow) and f.args[0] == var and f.args[1].is_constant():
        return True
    return False

def _detect_zero_times_inf(expr, var, point, direction):
    factors = expr.as_ordered_factors()
    if len(factors) < 2:
        return None
    zero_f, inf_f = None, None
    for f in factors:
        try:
            lv = sympy.limit(f, var, point, dir=direction)
        except Exception:
            continue
        if lv == 0 and zero_f is None:
            zero_f = f
        elif lv in (sympy.oo, -sympy.oo) and inf_f is None:
            inf_f = f
    if zero_f is None or inf_f is None:
        return None
    rest = sympy.Mul(*[f for f in factors if f is not zero_f and f is not inf_f])
    # Prefer putting a "simple power of var" factor's RECIPROCAL in the
    # denominator (clean derivative) and the other factor (often
    # transcendental) as the numerator -- minimizes derivative blow-up,
    # e.g. x*ln(x) -> ln(x)/(1/x), not x/(1/ln(x)).
    if _is_simple_power(zero_f, var) and not _is_simple_power(inf_f, var):
        return rest*inf_f, 1/zero_f
    return rest*zero_f, 1/inf_f

def _detect_exp_indeterminate(expr, var, point, direction):
    if not isinstance(expr, sympy.Pow):
        return None
    base, exp = expr.args
    try:
        bv = sympy.limit(base, var, point, dir=direction)
        ev = sympy.limit(exp, var, point, dir=direction)
    except Exception:
        return None
    if bv == 1 and ev in (sympy.oo, -sympy.oo): return ('1^\\infty', base, exp)
    if bv == 0 and ev == 0: return ('0^0', base, exp)
    if bv in (sympy.oo, -sympy.oo) and ev == 0: return ('\\infty^0', base, exp)
    return None

def compute_limit_steps(expr, var, point, direction='+-', max_iter=5):
    """Returns (steps: list of dict, final_result). The FINAL answer always
    comes from sympy's own limit() (Gruntz algorithm etc.) -- these steps
    are a pedagogical illustration of a standard technique (substitution,
    L'Hopital, and the standard rewrites for 0*inf / 1^inf / 0^0 / inf^0),
    not a claim about sympy's internal method, so the reported answer's
    correctness never depends on how far the shown technique gets."""
    steps = []
    try:
        direct = expr.subs(var, point)
    except Exception:
        direct = None
    steps.append({
        'kind': 'direct_substitution', 'expr_latex': sympy.latex(expr),
        'point_latex': sympy.latex(point),
        'substituted_latex': sympy.latex(direct) if direct is not None else None,
        'is_indeterminate': direct is None or str(direct) in ('nan', 'zoo'),
    })

    num, den = sympy.fraction(sympy.together(expr))
    iteration = 0
    exp_form_pending = False
    seen = set()
    while iteration < max_iter:
        try:
            nv = sympy.limit(num, var, point, dir=direction)
            dv = sympy.limit(den, var, point, dir=direction)
        except Exception:
            break
        form = _classify_ratio(nv, dv)

        if form:
            num_d, den_d = sympy.diff(num, var), sympy.diff(den, var)
            num_d, den_d = sympy.fraction(sympy.together(sympy.simplify(num_d/den_d)))
            steps.append({
                'kind': 'lhopital', 'form': form,
                'before_num_latex': sympy.latex(num), 'before_den_latex': sympy.latex(den),
                'after_num_latex': sympy.latex(num_d), 'after_den_latex': sympy.latex(den_d),
            })
            num, den = num_d, den_d
            iteration += 1
            continue

        current = sympy.together(num/den) if den != 1 else num
        sig = sympy.srepr(current)
        if sig in seen:
            break
        seen.add(sig)

        zti = _detect_zero_times_inf(current, var, point, direction)
        if zti:
            new_num, new_den = zti
            steps.append({
                'kind': 'rewrite_zero_times_inf', 'form': '0\\cdot\\infty',
                'before_latex': sympy.latex(current),
                'after_num_latex': sympy.latex(new_num), 'after_den_latex': sympy.latex(new_den),
            })
            num, den = new_num, new_den
            iteration += 1
            continue

        expf = _detect_exp_indeterminate(current, var, point, direction)
        if expf and not exp_form_pending:
            form_name, base, exp = expf
            inner = sympy.expand_log(exp*sympy.log(base), force=True)
            steps.append({
                'kind': 'rewrite_exponential', 'form': form_name,
                'original_latex': sympy.latex(current), 'exponent_form_latex': sympy.latex(inner),
            })
            exp_form_pending = True
            num, den = sympy.fraction(sympy.together(inner))
            iteration += 1
            continue

        break

    final = sympy.limit(expr, var, point, dir=direction)
    if exp_form_pending:
        steps.append({'kind': 'exponentiate_back'})
    steps.append({'kind': 'final', 'result_latex': sympy.latex(final), 'result_plain': str(final)})
    return steps, final

def _format_limit_steps(steps, var_name):
    """Convert the structured step data into human-readable strings for display.
    LaTeX fragments are wrapped in $...$ so the frontend can find and render
    them inline (see mhRenderMixedLatex in utils.js) without disturbing the
    plain English wrapped around them."""
    out = []
    for s in steps:
        k = s['kind']
        if k == 'direct_substitution':
            if s['is_indeterminate']:
                out.append(f"Try direct substitution ${var_name} = {s['point_latex']}$: gives an indeterminate form.")
            else:
                out.append(f"Direct substitution ${var_name} = {s['point_latex']}$ gives ${s['substituted_latex']}$ directly \u2014 no further work needed.")
        elif k == 'lhopital':
            out.append(
                f"This is a ${s['form']}$ indeterminate form. Apply L'H\u00f4pital's Rule (differentiate numerator and denominator separately): "
                f"$\\frac{{{s['before_num_latex']}}}{{{s['before_den_latex']}}} \\to \\frac{{{s['after_num_latex']}}}{{{s['after_den_latex']}}}$"
            )
        elif k == 'rewrite_zero_times_inf':
            out.append(
                f"This is a ${s['form']}$ indeterminate form. Rewrite as a quotient so L'H\u00f4pital's Rule applies: "
                f"${s['before_latex']} = \\dfrac{{{s['after_num_latex']}}}{{{s['after_den_latex']}}}$"
            )
        elif k == 'rewrite_exponential':
            out.append(
                f"This is a ${s['form']}$ indeterminate form. Using $f^g = e^{{g\\ln f}}$, the limit of the exponent determines the answer: "
                f"${s['original_latex']} = e^{{{s['exponent_form_latex']}}}$"
            )
        elif k == 'exponentiate_back':
            out.append("Exponentiate the limit of the rewritten exponent (raise e to that power) to get the final answer.")
        elif k == 'final':
            out.append(f"Therefore the limit is: ${s['result_latex']}$")
    return out


@app.route('/api/limit', methods=['POST'])
@limiter.limit("30 per minute")
def api_limit():
    data = request.get_json(silent=True)
    if not data or 'expression' not in data or 'point' not in data:
        return err("Provide 'expression' and 'point'")
    try:
        var_name = str(data.get('variable', 'x'))[:5]
        if not re.match(r'^[A-Za-z]$', var_name):
            return err("variable must be a single letter")
        x = sympy.Symbol(var_name)
        expr = _safe_sympify(str(data['expression'])[:MAX_EXPR_LEN], {var_name: x})
        point_str = str(data['point'])[:50]
        validate_expr_safety(point_str)
        point = sympy.oo if point_str.lower() in ('oo', 'inf', 'infinity') else \
                -sympy.oo if point_str.lower() in ('-oo', '-inf') else sympy.sympify(point_str)
        direction = data.get('direction', '+-')
        direction = direction if direction in ('+', '-') else '+-'
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            step_data, result = compute_limit_steps(expr, x, point, direction=direction)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        direct_sub = expr.subs(x, point)
        is_indeterminate = direct_sub.is_finite is False or str(direct_sub) in ('nan', 'zoo') or \
                            (hasattr(direct_sub, 'is_indeterminate') and direct_sub.is_indeterminate)
        # Special-case explanation for results that aren't a plain number —
        # otherwise these render as obscure notation (⟨-∞,∞⟩ or bare "zoo")
        # with no indication of what they actually mean.
        special_result_note = None
        if isinstance(result, AccumBounds):
            lo, hi = result.min, result.max
            if lo in (sympy.oo, -sympy.oo) or hi in (sympy.oo, -sympy.oo):
                special_result_note = ("This limit does not settle on a single value \u2014 the expression "
                                        "oscillates without bound as " + var_name + " approaches $" + sympy.latex(point) + "$" +
                                        ". The reported range $" + sympy.latex(result) + "$ means it takes arbitrarily "
                                        "large values (in magnitude) infinitely often, so no ordinary limit exists here.")
            else:
                special_result_note = ("This limit does not settle on a single value \u2014 the expression keeps "
                                        "oscillating between $" + sympy.latex(lo) + "$ and $" + sympy.latex(hi) + "$ as " +
                                        var_name + " approaches $" + sympy.latex(point) + "$, without ever settling on "
                                        "one value. The expression stays bounded here \u2014 it simply never converges.")
        elif result == sympy.zoo:
            try:
                left = sympy.limit(expr, x, point, dir='-')
                right = sympy.limit(expr, x, point, dir='+')
                special_result_note = ("The two-sided limit does not exist as a single signed value: "
                                        "from the left it approaches $" + sympy.latex(left) + "$, from the right $" +
                                        sympy.latex(right) + "$. Since the magnitude is unbounded but the sign "
                                        "depends on direction, SymPy reports this as complex infinity (zoo).")
            except Exception:
                special_result_note = "This limit does not exist as a single real value (unbounded magnitude, undefined sign)."
        return jsonify({
            "expression": sympy.latex(expr), "point": sympy.latex(point),
            "result": sympy.latex(result), "result_plain": str(result),
            "direct_substitution_note": "Direct substitution gives an indeterminate form \u2014 L'H\u00f4pital's rule or algebraic manipulation applies" if is_indeterminate else None,
            "special_result_note": special_result_note,
            "steps": _format_limit_steps(step_data, var_name),
        })
    except _TimeoutError:
        return err("Limit computation took too long", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Limit error: {e}")


@app.route('/api/dsolve', methods=['POST'])
@limiter.limit("20 per minute")
def api_dsolve():
    data = request.get_json(silent=True)
    if not data or 'equation' not in data:
        return err("Provide 'equation' (e.g. \"f(x).diff(x) + f(x)\" meaning that expression = 0, or use 'rhs' for the right-hand side)")
    try:
        var_name = str(data.get('variable', 'x'))[:5]
        func_name = str(data.get('function', 'f'))[:10]
        if not re.match(r'^[A-Za-z]$', var_name) or not re.match(r'^[A-Za-z]+$', func_name):
            return err("variable/function names must be plain letters")
        x = sympy.Symbol(var_name)
        f = sympy.Function(func_name)
        local_syms = {var_name: x, func_name: f}
        lhs_str = str(data['equation'])[:MAX_EXPR_LEN]
        rhs_str = str(data.get('rhs', '0'))[:MAX_EXPR_LEN]
        lhs = _safe_sympify(lhs_str, local_syms)
        rhs = _safe_sympify(rhs_str, local_syms)
        ode = sympy.Eq(lhs, rhs)
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            hints = sympy.classify_ode(ode, f(x))
            sol = sympy_dsolve(ode, f(x))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return jsonify({
            "equation": sympy.latex(ode), "solution": sympy.latex(sol),
            "solution_plain": str(sol), "classification": list(hints[:3]) if hints else [],
        })
    except _TimeoutError:
        return err("dsolve took too long \u2014 try a simpler ODE", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"ODE solver error: {e}")


@app.route('/api/laplace', methods=['POST'])
@limiter.limit("20 per minute")
def api_laplace():
    data = request.get_json(silent=True)
    if not data or 'expression' not in data:
        return err("Provide 'expression' (in terms of t)")
    try:
        t = sympy.Symbol('t', positive=True)
        s = sympy.Symbol('s', positive=True)
        expr = _safe_sympify(str(data['expression'])[:MAX_EXPR_LEN], {'t': t})
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            result = laplace_transform(expr, t, s, noconds=True)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return jsonify({
            "expression": sympy.latex(expr), "result": sympy.latex(result),
            "result_plain": str(result),
        })
    except _TimeoutError:
        return err("Laplace transform took too long", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Laplace transform error: {e}")


@app.route('/api/series', methods=['POST'])
@limiter.limit("20 per minute")
def api_series():
    data = request.get_json(silent=True)
    if not data or 'expression' not in data:
        return err("Provide 'expression'")
    try:
        var_name = str(data.get('variable', 'x'))[:5]
        if not re.match(r'^[A-Za-z]$', var_name):
            return err("variable must be a single letter")
        x = sympy.Symbol(var_name)
        expr = _safe_sympify(str(data['expression'])[:MAX_EXPR_LEN], {var_name: x})
        point_str = str(data.get('point', '0'))[:50]
        validate_expr_safety(point_str)
        point = sympy.sympify(point_str)
        n = int(data.get('n', 6))
        if n < 1 or n > 20:
            return err("n (number of terms) must be between 1 and 20")
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            s = expr.series(x, point, n)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return jsonify({"expression": sympy.latex(expr), "series": sympy.latex(s), "series_plain": str(s)})
    except _TimeoutError:
        return err("Series expansion took too long", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Series error: {e}")


@app.route('/api/vector-calc', methods=['POST'])
@limiter.limit("20 per minute")
def api_vector_calc():
    data = request.get_json(silent=True)
    if not data or 'operation' not in data:
        return err("Provide 'operation' (gradient/divergence/curl) and the relevant field components")
    try:
        from sympy.vector import CoordSys3D, gradient, divergence, curl
        N = CoordSys3D('N')
        op = data['operation']
        local_syms = {'x': N.x, 'y': N.y, 'z': N.z}
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            if op == 'gradient':
                phi_str = str(data.get('scalar', ''))[:MAX_EXPR_LEN]
                phi = _safe_sympify(phi_str, local_syms)
                result = gradient(phi)
            elif op in ('divergence', 'curl'):
                fx = _safe_sympify(str(data.get('fx', '0'))[:MAX_EXPR_LEN], local_syms)
                fy = _safe_sympify(str(data.get('fy', '0'))[:MAX_EXPR_LEN], local_syms)
                fz = _safe_sympify(str(data.get('fz', '0'))[:MAX_EXPR_LEN], local_syms)
                field = fx * N.i + fy * N.j + fz * N.k
                result = divergence(field) if op == 'divergence' else curl(field)
            else:
                return err("operation must be one of: gradient, divergence, curl")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return jsonify({"operation": op, "result": sympy.latex(result), "result_plain": str(result)})
    except _TimeoutError:
        return err("Vector calculus computation took too long", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Vector calculus error: {e}")


@app.route('/api/euler-lagrange', methods=['POST'])
@limiter.limit("20 per minute")
def api_euler_lagrange():
    data = request.get_json(silent=True)
    if not data or 'lagrangian' not in data:
        return err("Provide 'lagrangian' (in terms of y, y', and x \u2014 use Derivative(y(x),x) for y')")
    try:
        var_name = str(data.get('variable', 'x'))[:5]
        func_name = str(data.get('function', 'y'))[:10]
        if not re.match(r'^[A-Za-z]$', var_name) or not re.match(r'^[A-Za-z]+$', func_name):
            return err("variable/function names must be plain letters")
        x = sympy.Symbol(var_name)
        y = sympy.Function(func_name)
        local_syms = {var_name: x, func_name: y, 'Derivative': sympy.Derivative}
        L = _safe_sympify(str(data['lagrangian'])[:MAX_EXPR_LEN], local_syms)
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(SYMPY_TIMEOUT_SECONDS)
        try:
            eq = euler_equations(L, y(x), x)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return jsonify({
            "lagrangian": sympy.latex(L),
            "euler_lagrange_equation": [sympy.latex(e) for e in eq],
        })
    except _TimeoutError:
        return err("Euler-Lagrange derivation took too long", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Euler-Lagrange error: {e}")


# ══════════════════════════════════════════════════════════════════
# NUMBER THEORY & CRYPTOGRAPHY
# Per the implementation matrix: SymPy is the clear winner here —
# factorint/totient/primitive_root/is_quad_residue/crt all native.
# These take plain integers, not expression strings, so the sympify-
# RCE class of attack doesn't apply the same way — but inputs are
# still bounded to keep factoring/primality-testing fast and to stop
# someone sending a 500-digit number and tying up a worker.
# ══════════════════════════════════════════════════════════════════
MAX_NT_INT = 10**15      # bound for factorization / totient / primitive root / QR
MAX_QR_ENUM_MODULUS = 100_000  # separate, much tighter bound: listing every quadratic
                                # residue mod p is an O(p) scan, unlike is_quad_residue/
                                # the Legendre symbol (fast for any p via modular
                                # exponentiation) -- without this, p up to MAX_NT_INT
                                # (10**15) would hang a worker on a single request.
MAX_RSA_PRIME = 10**6    # demonstrator only — small by design, matches the
                          # roadmap's own "SymPy now, SageMath/PARI-GP in
                          # Phase 5 for real key sizes" phasing


def _safe_int(v, max_val, name="value"):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if abs(n) > max_val:
        raise ValueError(f"{name} is too large (max {max_val})")
    return n


@app.route('/api/factorize', methods=['POST'])
@limiter.limit("30 per minute")
def api_factorize():
    data = request.get_json(silent=True)
    if not data or 'n' not in data:
        return err("Provide 'n'")
    try:
        n = _safe_int(data['n'], MAX_NT_INT, "n")
        if n < 2:
            return err("n must be \u2265 2")
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(5)
        try:
            factors = sympy.factorint(n)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        steps = []
        running = n
        for p, e in sorted(factors.items()):
            for _ in range(e):
                steps.append({"divide_by": p, "before": running, "after": running // p})
                running //= p
        factor_str = ' \u00d7 '.join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(factors.items()))
        return jsonify({
            "n": n, "factors": {str(k): v for k, v in factors.items()},
            "factor_str": factor_str, "steps": steps,
            "is_prime": len(factors) == 1 and list(factors.values())[0] == 1,
        })
    except _TimeoutError:
        return err("Factorization took too long \u2014 try a smaller number", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Factorization error: {e}")


@app.route('/api/totient', methods=['POST'])
@limiter.limit("30 per minute")
def api_totient():
    data = request.get_json(silent=True)
    if not data or 'n' not in data:
        return err("Provide 'n'")
    try:
        n = _safe_int(data['n'], MAX_NT_INT, "n")
        if n < 1:
            return err("n must be \u2265 1")
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(5)
        try:
            factors = sympy.factorint(n)
            phi = sympy.totient(n)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        # phi(n) = n * prod(1 - 1/p) over distinct prime factors
        terms = [f"(1 - 1/{p})" for p in sorted(factors)]
        formula = f"{n} \u00d7 " + " \u00d7 ".join(terms) if terms else str(n)
        return jsonify({
            "n": n, "phi": int(phi),
            "prime_factors": sorted(factors.keys()),
            "formula": formula,
        })
    except _TimeoutError:
        return err("Totient computation took too long \u2014 try a smaller number", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Totient error: {e}")


@app.route('/api/primitive-root', methods=['POST'])
@limiter.limit("30 per minute")
def api_primitive_root():
    data = request.get_json(silent=True)
    if not data or 'n' not in data:
        return err("Provide 'n'")
    try:
        n = _safe_int(data['n'], MAX_NT_INT, "n")
        if n < 1:
            return err("n must be \u2265 1")
        old_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(5)
        try:
            g = sympy.primitive_root(n)
            if g is not None:
                phi = int(sympy.totient(n))
                order_check = [{"d": d, "g^d mod n": pow(g, d, n)} for d in sorted(sympy.divisors(phi))]
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        if g is None:
            return jsonify({"n": n, "exists": False,
                            "msg": f"No primitive root exists mod {n} (only exists for n = 1, 2, 4, p^k, or 2p^k)"})
        return jsonify({"n": n, "exists": True, "g": g, "phi": phi, "order_check": order_check})
    except _TimeoutError:
        return err("Search took too long \u2014 try a smaller n", 408)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Primitive root error: {e}")


@app.route('/api/quad-residue', methods=['POST'])
@limiter.limit("30 per minute")
def api_quad_residue():
    data = request.get_json(silent=True)
    if not data or 'a' not in data or 'p' not in data:
        return err("Provide 'a' and 'p'")
    try:
        a = _safe_int(data['a'], MAX_NT_INT, "a")
        p = _safe_int(data['p'], MAX_NT_INT, "p")
        if p < 2 or not sympy.isprime(p):
            return err("p must be a prime \u2265 2 (Legendre symbol requires an odd prime modulus)")
        is_qr = sympy.is_quad_residue(a, p)
        # Euler's criterion: a^((p-1)/2) mod p  ->  1 (QR), p-1 (non-QR), 0 (a≡0)
        legendre_val = pow(a, (p - 1) // 2, p)
        legendre = 0 if a % p == 0 else (1 if legendre_val == 1 else -1)
        resp = {
            "a": a, "p": p, "is_quad_residue": bool(is_qr),
            "legendre_symbol": legendre,
            "eulers_criterion": f"{a}^{(p-1)//2} mod {p} = {legendre_val}",
        }
        if p <= MAX_QR_ENUM_MODULUS:
            resp["quadratic_residues_mod_p"] = sorted(set((k * k) % p for k in range(1, p)))
        else:
            resp["quadratic_residues_mod_p"] = None
            resp["quadratic_residues_note"] = f"p is too large to list every residue here (max {MAX_QR_ENUM_MODULUS} for the full list) — the checks above still hold for any p."
        return jsonify(resp)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Quadratic residue error: {e}")


@app.route('/api/crt', methods=['POST'])
@limiter.limit("30 per minute")
def api_crt():
    data = request.get_json(silent=True)
    if not data or 'remainders' not in data or 'moduli' not in data:
        return err("Provide 'remainders' and 'moduli' (parallel arrays)")
    try:
        remainders = data['remainders']
        moduli = data['moduli']
        if len(remainders) != len(moduli):
            return err("'remainders' and 'moduli' must be the same length")
        if len(remainders) < 2 or len(remainders) > 10:
            return err("Provide 2 to 10 congruences")
        rs = [_safe_int(r, MAX_NT_INT, "remainder") for r in remainders]
        ms = [_safe_int(m, MAX_NT_INT, "modulus") for m in moduli]
        if any(m < 2 for m in ms):
            return err("All moduli must be \u2265 2")
        # pairwise coprimality check (sympy.crt requires it for a unique solution)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                if sympy.gcd(ms[i], ms[j]) != 1:
                    return err(f"Moduli {ms[i]} and {ms[j]} are not coprime \u2014 CRT needs pairwise coprime moduli")
        from sympy.ntheory.modular import crt as sympy_crt
        result = sympy_crt(ms, rs)
        if result is None:
            return err("No solution exists for this system")
        x, M = result
        # Build pairwise-combination steps for the UI (combine first two, then fold in each remaining)
        steps = []
        cur_r, cur_m = rs[0], ms[0]
        for i in range(1, len(ms)):
            from sympy.ntheory.modular import crt as step_crt
            nxt = step_crt([cur_m, ms[i]], [cur_r, rs[i]])
            cur_r, cur_m = int(nxt[0]), int(nxt[1])
            steps.append({"combined_with": {"r": rs[i], "m": ms[i]}, "result": {"x": cur_r, "mod": cur_m}})
        return jsonify({"x": int(x), "M": int(M), "steps": steps})
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"CRT error: {e}")


@app.route('/api/rsa', methods=['POST'])
@limiter.limit("20 per minute")
def api_rsa():
    data = request.get_json(silent=True)
    if not data:
        return err("No data provided")
    try:
        p = _safe_int(data.get('p'), MAX_RSA_PRIME, "p")
        q = _safe_int(data.get('q'), MAX_RSA_PRIME, "q")
        if not sympy.isprime(p) or not sympy.isprime(q):
            return err("p and q must both be prime")
        if p == q:
            return err("p and q must be different primes")
        n = p * q
        phi = (p - 1) * (q - 1)
        e = data.get('e')
        if e is None:
            e = 65537 if sympy.gcd(65537, phi) == 1 else 17
        else:
            e = _safe_int(e, phi, "e")
        if sympy.gcd(e, phi) != 1:
            return err(f"e={e} is not coprime with \u03c6(n)={phi} \u2014 choose a different e")
        d = int(sympy.mod_inverse(e, phi))

        result = {"p": p, "q": q, "n": n, "phi": phi, "e": e, "d": d}

        mode = data.get('mode', 'keygen')
        if mode == 'encrypt' and 'message' in data:
            m = _safe_int(data['message'], n - 1, "message")
            if m >= n:
                return err(f"message must be less than n={n}")
            c = pow(m, e, n)
            result.update({"mode": "encrypt", "message": m, "ciphertext": c})
        elif mode == 'decrypt' and 'ciphertext' in data:
            c = _safe_int(data['ciphertext'], n - 1, "ciphertext")
            m = pow(c, d, n)
            result.update({"mode": "decrypt", "ciphertext": c, "message": m})
        return jsonify(result)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"RSA error: {e}")


@app.route('/api/miller-rabin', methods=['POST'])
@limiter.limit("30 per minute")
def api_miller_rabin():
    data = request.get_json(silent=True)
    if not data or 'n' not in data:
        return err("Provide 'n'")
    try:
        n = _safe_int(data['n'], 10**30, "n")  # isprime handles big n fine, no factoring needed
        if n < 2:
            return jsonify({"n": n, "prime": False, "steps": []})
        witnesses = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
        witnesses = [w for w in witnesses if w < n - 1] or [2]
        if n in (2, 3):
            return jsonify({"n": n, "prime": True, "steps": []})
        if n % 2 == 0:
            return jsonify({"n": n, "prime": False, "steps": [{"note": "n is even"}]})
        d, r = n - 1, 0
        while d % 2 == 0:
            d //= 2
            r += 1
        steps = []
        is_prime_result = True
        for a in witnesses:
            x = pow(a, d, n)
            seq = [x]
            step = {"witness": a}
            if x == 1 or x == n - 1:
                step["sequence"] = seq
                step["result"] = "inconclusive (passes this witness)"
                steps.append(step)
                continue
            composite_witness = True
            for _ in range(r - 1):
                x = pow(x, 2, n)
                seq.append(x)
                if x == n - 1:
                    composite_witness = False
                    break
            step["sequence"] = seq
            step["result"] = "COMPOSITE \u2014 witness found" if composite_witness else "passes this witness"
            steps.append(step)
            if composite_witness:
                is_prime_result = False
                break
        return jsonify({"n": n, "d": d, "r": r, "prime": is_prime_result, "steps": steps})
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Miller-Rabin error: {e}")


@app.errorhandler(429)
def handle_rate_limit(e):
    return jsonify({"error": "Too many requests — please slow down and try again shortly."}), 429


@app.errorhandler(413)
def handle_too_large(e):
    return jsonify({"error": "Request is too large."}), 413


@app.errorhandler(Exception)
def handle_uncaught(e):
    app.logger.error(traceback.format_exc())
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
