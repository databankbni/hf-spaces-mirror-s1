# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

用法：pyinstaller --clean build.spec
输出：dist/AgentFlow.exe
"""

import os
import sys

block_cipher = None

# 项目根目录
ROOT = os.path.dirname(os.path.abspath(SPEC))

# 前端构建产物
STATIC_DIR = os.path.join(ROOT, "client", "dist")

a = Analysis(
    # 入口脚本
    [os.path.join(ROOT, "server", "app", "desktop.py")],

    # 搜索路径
    pathex=[
        os.path.join(ROOT, "server"),
        os.path.join(ROOT, "agentflow"),
        ROOT,
    ],

    binaries=[],

    # 打包数据文件
    datas=[
        # 前端静态文件 → static/
        (STATIC_DIR, "static"),
        # 默认配置文件
        (os.path.join(ROOT, "server", "app", "default_config.json"), "."),
        # 默认预设（skills + agents）
        (os.path.join(ROOT, "server", "app", "default_presets"), "default_presets"),
        # agentflow 包（作为数据文件，因为是 -e 安装的）
        (os.path.join(ROOT, "agentflow"), "agentflow"),
        # Alembic 迁移（如果需要）
        (os.path.join(ROOT, "server", "alembic"), "alembic"),
    ],

    hiddenimports=[
        # Uvicorn 子模块
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # SQLite
        "aiosqlite",
        "sqlite3",
        # SQLAlchemy 方言
        "sqlalchemy.dialects.sqlite",
        # FastAPI
        "fastapi",
        "fastapi.staticfiles",
        "fastapi.responses",
        "starlette.middleware.cors",
        # pywebview
        "webview",
        # agentflow
        "agentflow",
        "agentflow.agent",
        "agentflow.llm.openai_adapter",
        "agentflow.plugins.memory_plugin",
        "agentflow.specs",
        # 应用模块
        "app.main",
        "app.desktop",
        "app.core.config",
        "app.core.database",
        "app.api.v1.settings",
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大包
        "torch",
        "tensorflow",
        "transformers",
        "matplotlib",
        "PIL",
        "numpy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AgentFlow",
)
