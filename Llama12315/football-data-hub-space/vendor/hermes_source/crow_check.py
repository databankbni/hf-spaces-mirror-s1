#!/usr/bin/env python3
"""crow-screener 快速查询器 — 给定match_id, 查是否触发crow弱形式让球方筛选

用法:
  python3 crow_check.py <match_id> [--data crow_today.json]
  python3 crow_check.py --batch              # 生成数据
  python3 crow_check.py --batch --verbose    # 生成数据+详细错误
  python3 crow_check.py --check-available    # 检测crow-screener是否可用

输出: {"triggered": bool, "rating": "A/B/C/None", "detail": {...}}

降级规则:
  - 如果 crow-screener 不可用（Playwright Chromium 未安装），
    --batch 返回详细错误而非只有 batch_ok=false。
  - 主预测流程不得因 crow_data_unavailable 阻塞。
"""
import json, sys, os, subprocess

DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'crow_today.json')
SCRIPT_DIR = '/Users/LL/.hermes/profiles/football/skills/autonomous-ai-agents/crow-weak-form-favorite-screener/tools'
CROW_SCRIPT = os.path.join(SCRIPT_DIR, 'titan007_crow_today.py')
LOCAL_RUNTIME = os.path.expanduser('~/.hermes/profiles/football/workspace/scripts/hermes_python.sh')
PYTHON = os.environ.get('HERMES_PYTHON') or (LOCAL_RUNTIME if os.path.isfile(LOCAL_RUNTIME) else sys.executable)


# ═══════════════════════════════════════════════
# 检测 Playwright Chromium 是否安装
# ═══════════════════════════════════════════════

def check_playwright_chromium_available() -> dict:
    """检测 playwright 库 + chromium 浏览器是否可用.

    Returns:
        {
            "crow_screener_available": True/False,
            "reason": "",
            "playwright_import_ok": True/False,
            "chromium_executable_ok": True/False,
            "error": "",
            "install_hint": "python -m playwright install chromium",
            "requires_user_permission": True
        }
    """
    result = {
        "crow_screener_available": False,
        "playwright_import_ok": False,
        "chromium_executable_ok": False,
        "error": "",
        "install_hint": "python -m playwright install chromium",
        "requires_user_permission": True,
        "reason": "",
    }

    # 1. Try import playwright
    try:
        import playwright
        result["playwright_import_ok"] = True
    except ImportError:
        result["error"] = "playwright package not installed"
        result["reason"] = "playwright_package_missing"
        return result

    # 2. Try to find chromium executable - use simple shell check
    try:
        ver_check = subprocess.run(
            [PYTHON, "-c", """
import sys
try:
    from playwright.sync_api import sync_playwright
    print("sync_api_ok")
except ImportError:
    try:
        import playwright
        print("playwright_imported_but_no_sync_api")
    except:
        print("no_playwright")
"""],
            capture_output=True, text=True, timeout=15
        )
        stdout = ver_check.stdout.strip()

        if "sync_api_ok" in stdout:
            # Playwright sync API works - try launching a browser to check
            launch_check = subprocess.run(
                [PYTHON, "-c", """
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        # Just check if chromium path exists, don't actually launch
        exec_path = p.chromium.executable_path
        import os
        if os.path.exists(exec_path):
            print("chromium_ok")
        else:
            print("chromium_not_found:" + exec_path)
except Exception as e:
    print("chromium_error:" + str(e)[:100])
"""],
                capture_output=True, text=True, timeout=15
            )
            if "chromium_ok" in launch_check.stdout:
                result["chromium_executable_ok"] = True
            elif "chromium_error" in launch_check.stdout:
                result["error"] = launch_check.stdout.strip()
        else:
            result["error"] = f"playwright sync_api not available: {stdout}"
    except Exception as exc:
        result["error"] = str(exc)[:200]

    if result["chromium_executable_ok"]:
        result["crow_screener_available"] = True
        result["reason"] = "playwright_chromium_available"
        result["requires_user_permission"] = False
    else:
        result["reason"] = "playwright_chromium_missing"
        if not result["error"]:
            result["error"] = "chromium browser binary not installed for playwright"

    return result


# ═══════════════════════════════════════════════
# 数据生成（改进版 — 暴露 stderr）
# ═══════════════════════════════════════════════

def ensure_data() -> bool:
    """原版 ensure_data — 只返回 bool（兼容旧调用者）"""
    result = _run_batch_subprocess()
    return result.get("batch_ok", False)


def ensure_data_verbose() -> dict:
    """改进版 ensure_data — 返回详细错误信息。

    Returns:
        {
            "batch_ok": True/False,
            "error_type": "",
            "returncode": int,
            "stdout_tail": "...",
            "stderr_tail": "...",
            "data_file_exists": True/False,
            "data_file": str,
            "hint": "",
        }
    """
    return _run_batch_subprocess()


def _run_batch_subprocess() -> dict:
    """运行 crow batch 子进程，返回详细结果。"""
    # 先检测 playwright chromium 是否可用
    avail = check_playwright_chromium_available()
    if not avail["crow_screener_available"]:
        return {
            "batch_ok": False,
            "error_type": avail["reason"],
            "playwright_chromium_available": False,
            "error": avail["error"],
            "install_hint": avail["install_hint"],
            "requires_user_permission": True,
            "data_file_exists": os.path.exists(DATA_FILE),
            "data_file": DATA_FILE,
            "fallback": "multi_company_analyzer_only",
        }

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    try:
        result = subprocess.run(
            [PYTHON, CROW_SCRIPT, '--out', DATA_FILE, '--timezone', 'Asia/Shanghai',
             '--min-delay', '600', '--max-delay', '900'],
            capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR
        )
    except subprocess.TimeoutExpired:
        return {
            "batch_ok": False,
            "error_type": "crow_batch_timeout",
            "error": "subprocess timed out after 120s",
            "data_file_exists": os.path.exists(DATA_FILE),
            "data_file": DATA_FILE,
        }
    except FileNotFoundError:
        return {
            "batch_ok": False,
            "error_type": "crow_script_not_found",
            "error": f"crow script not found: {CROW_SCRIPT}",
            "data_file_exists": os.path.exists(DATA_FILE),
            "data_file": DATA_FILE,
        }

    data_file_exists = os.path.exists(DATA_FILE)

    if result.returncode != 0:
        return {
            "batch_ok": False,
            "error_type": "crow_batch_subprocess_failed",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-1000:] if result.stdout else "",
            "stderr_tail": result.stderr[-2000:] if result.stderr else "",
            "data_file_exists": data_file_exists,
            "data_file": DATA_FILE,
            "fallback": "multi_company_analyzer_only",
            "hint": "If stderr mentions 'playwright install' or browser binary, run: python -m playwright install chromium",
        }

    if not data_file_exists:
        return {
            "batch_ok": False,
            "error_type": "crow_data_file_missing_after_batch",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-1000:] if result.stdout else "",
            "stderr_tail": result.stderr[-2000:] if result.stderr else "",
            "data_file_exists": False,
            "data_file": DATA_FILE,
        }

    return {
        "batch_ok": True,
        "error_type": "",
        "returncode": 0,
        "data_file_exists": True,
        "data_file": DATA_FILE,
        "fallback": "none",
    }


# ═══════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════

def check_match(match_id, data_path=None):
    """查单场是否触发crow筛选"""
    path = data_path or DATA_FILE
    if not os.path.exists(path):
        return {'triggered': False, 'error': 'no_data_file', 'hint': 'run --batch first'}

    with open(path) as f:
        data = json.load(f)

    matches = data.get('matches', data) if isinstance(data, dict) else data
    if isinstance(matches, dict):
        matches = list(matches.values())

    for m in matches:
        mid = str(m.get('match_id', ''))
        if mid == str(match_id):
            rating = m.get('rating', m.get('grade', 'None'))
            return {
                'triggered': rating in ('A', 'B', 'C'),
                'rating': rating,
                'detail': {
                    'home': m.get('home_team', m.get('home', '?')),
                    'away': m.get('away_team', m.get('away', '?')),
                    'league': m.get('league', '?'),
                    'handicap': m.get('handicap', '?'),
                    'home_water': m.get('home_water', '?'),
                    'score': m.get('score', m.get('total_score', '?')),
                }
            }
    return {'triggered': False, 'rating': 'None', 'detail': {}}


# ═══════════════════════════════════════════════
# 降级状态（供主流程调用）
# ═══════════════════════════════════════════════

def get_crow_screener_status() -> dict:
    """返回 crow-screener 的整体可用状态。

    供主预测流程在最终报告中输出：
    {
        "crow_screener": {
            "enabled": True,
            "available": False,
            "status": "crow_data_unavailable",
            "reason": "playwright_chromium_missing",
            "blocking": False,
            "fallback": "multi_company_analyzer_only"
        }
    }
    """
    avail = check_playwright_chromium_available()
    data_exists = os.path.exists(DATA_FILE)

    if avail["crow_screener_available"] and data_exists:
        return {
            "enabled": True,
            "available": True,
            "status": "crow_data_ready",
            "reason": "",
            "blocking": False,
            "fallback": "none",
        }
    elif avail["crow_screener_available"] and not data_exists:
        return {
            "enabled": True,
            "available": False,
            "status": "crow_data_not_generated",
            "reason": "batch_not_run",
            "blocking": False,
            "fallback": "multi_company_analyzer_only",
            "hint": "run crow_check.py --batch first",
        }
    else:
        return {
            "enabled": True,
            "available": False,
            "status": "crow_data_unavailable",
            "reason": avail.get("reason", "playwright_chromium_missing"),
            "blocking": False,
            "fallback": "multi_company_analyzer_only",
            "install_hint": avail.get("install_hint", "python -m playwright install chromium"),
            "requires_user_permission": avail.get("requires_user_permission", True),
        }


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    if '--check-available' in sys.argv:
        result = get_crow_screener_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    if '--batch' in sys.argv:
        verbose = '--verbose' in sys.argv
        if verbose:
            result = ensure_data_verbose()
        else:
            # back-compat: old callers expect just batch_ok
            ok = ensure_data()
            result = {'batch_ok': ok, 'file': DATA_FILE}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    mid = sys.argv[1] if len(sys.argv) > 1 else None
    dp = None
    for i, arg in enumerate(sys.argv):
        if arg == '--data' and i + 1 < len(sys.argv):
            dp = sys.argv[i + 1]
    if not mid:
        print(json.dumps({'error': 'no match_id'}))
        sys.exit(1)
    result = check_match(mid, dp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
