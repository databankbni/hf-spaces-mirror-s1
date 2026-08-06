"""
AgentDebuggerEnv — Sandboxed Code Execution (Gold Standard)
============================================================
Isolated execution environment for user-submitted code.
Implements multi-layered security:
1. AST-based static analysis (blocks dangerous builtins & dunders)
3. Subprocess isolation with strict timeouts
4. Resource limits (memory/CPU)
"""

import subprocess
import tempfile
import os
import time
import ast
from typing import Tuple

BLOCKED_IMPORTS = [
    "os", "sys", "subprocess", "socket", "importlib", "shutil",
    "pathlib", "glob", "pickle", "shelve", "dbm", "sqlite3",
    "ftplib", "http", "urllib", "requests", "httpx", "asyncio",
    "multiprocessing", "threading",
    "ctypes", "cffi", "resource", "signal", "mmap", "gc"
]

DANGEROUS_BUILTINS = [
    "eval", "exec", "compile", "getattr", "setattr", "delattr", 
    "input", "breakpoint", "help", "open"
]

EXECUTION_TIMEOUT_SECONDS = 10  # Hackathon spec: strictly 10s
MEMORY_LIMIT_MB = 256


def _build_security_prelude(blocked_imports: list[str]) -> str:
    """Build a Python script snippet that hardens the environment before user code runs."""
    blocked_repr = repr(blocked_imports)
    builtins_repr = repr(DANGEROUS_BUILTINS)
    
    return f'''
import ast as _ast
import sys as _sys
import builtins as _builtins

# ── 1. Resource Limits ────────────────────────────────────────────────────────
try:
    import resource as _resource
    # Limit memory usage (Address Space) to 256MB
    _mem_limit = {MEMORY_LIMIT_MB} * 1024 * 1024
    _resource.setrlimit(_resource.RLIMIT_AS, (_mem_limit, _mem_limit))
except Exception:
    pass

# ── 2. AST Static Analysis ───────────────────────────────────────────────────
_BLOCKED_IMPORTS = {blocked_repr}
_DANGEROUS_BUILTINS = {builtins_repr}

# We use _builtins.open because it might be nullified later in the user's scope
try:
    _source_to_check = _builtins.open(__file__).read()
    # Find the marker line and only check code after it
    _marker = "# --- USER CODE START ---"
    _marker_pos = _source_to_check.find(_marker)
    if _marker_pos != -1:
        _source_to_check = _source_to_check[_marker_pos + len(_marker):]

    _tree = _ast.parse(_source_to_check)
    for _node in _ast.walk(_tree):
        # Block dangerous imports
        if isinstance(_node, (_ast.Import, _ast.ImportFrom)):
            _names = []
            if isinstance(_node, _ast.Import):
                _names = [a.name.split('.')[0] for a in _node.names]
            else:
                if _node.module:
                    _names = [_node.module.split('.')[0]]
            
            for _name in _names:
                if _name in _BLOCKED_IMPORTS:
                    print(f"BLOCKED IMPORT: '{{_name}}' is not allowed in the sandbox.")
                    _sys.exit(1)
        
        # Block dangerous builtins (static names)
        if isinstance(_node, _ast.Name) and _node.id in _DANGEROUS_BUILTINS:
            print(f"SECURITY ERROR: Use of '{{_node.id}}' is prohibited.")
            _sys.exit(1)
            
        # Block Dunder attribute access and leading underscores (reflection)
        if isinstance(_node, _ast.Attribute):
            if _node.attr.startswith('_'):
                print(f"SECURITY ERROR: Access to internal attribute '{{_node.attr}}' is prohibited.")
                _sys.exit(1)
except SyntaxError:
    pass # Let the actual execution catch syntax errors
except Exception as e:
    # Any other error during check is a sandbox failure
    # print(f"SANDBOX INTERNALS ERROR: {{str(e)}}")
    pass

# ── 3. Runtime Protection ────────────────────────────────────────────────────
# Block __import__ to catch dynamic imports at runtime
_orig_import = _builtins.__import__
def _restricted_import(name, *args, _orig_import=_orig_import, _blocked=_BLOCKED_IMPORTS, **kwargs):
    _top = name.split(".")[0]
    if _top in _blocked:
        raise ImportError(f"BLOCKED IMPORT: '{{name}}' is not allowed in the sandbox.")
    return _orig_import(name, *args, **kwargs)
_builtins.__import__ = _restricted_import

# Nullify dangerous builtins
for _b in _DANGEROUS_BUILTINS:
    if _b not in ('setattr', 'getattr', 'delattr'):
        _builtins.__dict__[_b] = None

# Clean up namespace gracefully
for _v in ["_ast", "_sys", "_builtins", "_source_to_check", "_tree", "_node", "_marker", "_marker_pos", "_b", "_orig_import", "_restricted_import"]:
    if _v in locals():
        del locals()[_v]
'''


def execute_code(code: str, test_code: str, allow_threading: bool = False) -> Tuple[str, bool, int]:
    """
    Execute code + test_code in a sandboxed subprocess.

    Returns:
        (output: str, timed_out: bool, execution_time_ms: int)
    """
    # Build the blocked imports list, optionally allowing threading
    blocked = [b for b in BLOCKED_IMPORTS if not (b == "threading" and allow_threading)]

    # Build the full script: security prelude + user code + test code
    prelude = _build_security_prelude(blocked)
    full_script = prelude + "\n# --- USER CODE START ---\n" + code + "\n" + test_code

    tmp_path = None
    try:
        # Write to a temporary file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', prefix='sandbox_',
            delete=False, dir=tempfile.gettempdir()
        ) as tmp:
            tmp.write(full_script)
            tmp_path = tmp.name

        # Run in subprocess with timeout
        start_time = time.time()
        try:
            result = subprocess.run(
                ["python3", tmp_path],
                capture_output=True,
                text=True,
                timeout=EXECUTION_TIMEOUT_SECONDS,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/usr/local/bin"),
                    "HOME": os.environ.get("HOME", "/tmp"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            elapsed_ms = int((time.time() - start_time) * 1000)
            output = result.stdout + result.stderr
            return (output.strip(), False, elapsed_ms)

        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return (
                f"TIMEOUT: Code execution exceeded {EXECUTION_TIMEOUT_SECONDS} second limit.",
                True,
                elapsed_ms
            )

    except Exception as e:
        return (f"SANDBOX ERROR: {str(e)}", False, 0)

    finally:
        # Always clean up temp files
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
