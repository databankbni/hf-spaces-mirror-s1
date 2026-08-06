"""
桌面应用入口

使用 pywebview 创建原生窗口，后端 FastAPI 在后台线程运行。
双击 AgentFlow.exe 即可启动，无需安装任何依赖。

用法：
  开发测试：cd server && python -m app.desktop
  打包后：  直接运行 AgentFlow.exe
"""

import sys
import os
import socket
import threading
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _setup_logging():
    """配置日志：打包模式写文件，开发模式输出到控制台"""
    data_dir = Path.home() / "AgentFlow" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = data_dir / "agentflow.log"

    handlers: list[logging.Handler] = [logging.FileHandler(str(log_file), encoding="utf-8")]
    if not getattr(sys, "frozen", False):
        # 开发模式也输出到控制台
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _find_free_port() -> int:
    """找一个可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_data_dir() -> str:
    """确保数据目录存在，返回 SQLite 数据库路径"""
    data_dir = Path.home() / "AgentFlow" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "agentflow.db")


def _start_server(port: int):
    """在后台线程启动 FastAPI + Uvicorn"""
    try:
        import uvicorn

        from app.main import app
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False,
        )
    except Exception as e:
        logger.exception("Server failed to start: %s", e)


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """等待服务启动完成"""
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    return False


def main():
    """桌面应用主入口"""
    # 无控制台模式下（console=False），stdout/stderr 为 None
    # 必须先重定向，否则 uvicorn 的 formatter 会崩溃
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    # Windows UTF-8 支持
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 配置日志（打包模式写入 ~/AgentFlow/data/agentflow.log）
    _setup_logging()

    # 设置数据目录
    db_path = _setup_data_dir()
    os.environ.setdefault("SQLITE_PATH", db_path)

    # 找可用端口
    port = _find_free_port()
    logger.info("Starting AgentFlow on port %d", port)

    # 后台启动 FastAPI
    server_thread = threading.Thread(target=_start_server, args=(port,), daemon=True)
    server_thread.start()

    # 等待服务就绪
    if not _wait_for_server(port):
        logger.error("Server startup timeout")
        # 弹窗提示错误
        try:
            import webview
            webview.create_window(
                "AgentFlow - 错误",
                html="<div style='display:flex;align-items:center;justify-content:center;height:100vh;font-family:system-ui;'><div style='text-align:center;'><h2>启动失败</h2><p>服务启动超时，请查看日志：</p><code>~/AgentFlow/data/agentflow.log</code></div></div>",
                width=500,
                height=300,
            )
            webview.start()
        except Exception:
            pass
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    logger.info("AgentFlow ready at %s", url)

    # 打开原生窗口
    import webview
    webview.create_window(
        "AgentFlow",
        url,
        width=1400,
        height=900,
        min_size=(800, 600),
        text_select=True,
    )
    webview.start(debug=False)

    logger.info("AgentFlow closed")
    sys.exit(0)


if __name__ == "__main__":
    main()
