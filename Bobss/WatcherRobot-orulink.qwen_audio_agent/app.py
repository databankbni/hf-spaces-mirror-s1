"""Managed WatcheRobot Application entrypoint for Qwen Audio Agent."""

import asyncio
from urllib.parse import urlparse

from watcherobot.application import ApplicationContext

from qwen_audio_agent.configuration import BridgeConfiguration
from qwen_audio_agent.configuration import DEFAULT_GATEWAY_URL
from qwen_audio_agent.diagnostics import (
    ApplicationDiagnosticsServer,
    DiagnosticsState,
)
from qwen_audio_agent.gateway_bootstrap import (
    GatewayBootstrapError,
    GatewayRuntimeManager,
)
from qwen_audio_agent.runtime import BridgeApplicationRuntime
from qwen_audio_agent.settings import (
    GatewaySettingsError,
    GatewaySettingsStore,
    TouchInterruptSettingsError,
    TouchInterruptSettingsStore,
    VadSettingsError,
    VadSettingsStore,
    apply_gateway_settings_to_environment,
    apply_touch_interrupt_settings_to_environment,
    apply_vad_settings_to_environment,
)


def _gateway_health_url(websocket_url: str) -> str:
    parsed = urlparse(websocket_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{scheme}://{parsed.netloc}/api/health"


async def main() -> None:
    gateway_settings_store = GatewaySettingsStore.from_environment()
    settings_store = VadSettingsStore.from_environment()
    touch_settings_store = TouchInterruptSettingsStore.from_environment()
    try:
        active_gateway_settings = gateway_settings_store.load()
        apply_gateway_settings_to_environment(active_gateway_settings)
    except GatewaySettingsError as exc:
        raise RuntimeError(f"Gateway 参数文件无效：{exc}") from exc
    try:
        active_vad_settings = apply_vad_settings_to_environment(settings_store)
    except VadSettingsError as exc:
        raise RuntimeError(f"VAD 参数文件无效：{exc}") from exc
    try:
        active_touch_settings = apply_touch_interrupt_settings_to_environment(
            touch_settings_store
        )
    except TouchInterruptSettingsError as exc:
        raise RuntimeError(f"触摸打断参数文件无效：{exc}") from exc
    configuration = BridgeConfiguration.from_environment()
    diagnostics = DiagnosticsState()
    diagnostics_server = None
    gateway_runtime = None
    async with ApplicationContext.from_environment() as app:
        diagnostics.set_status("application", "ready", "Application 运行中")
        if configuration.diagnostics_enabled:
            diagnostics_server = ApplicationDiagnosticsServer(
                diagnostics,
                port=configuration.diagnostics_port,
                daemon_control_url=configuration.daemon_control_url,
                settings_store=settings_store,
                active_vad_settings=active_vad_settings,
                touch_settings_store=touch_settings_store,
                active_touch_settings=active_touch_settings,
                gateway_settings_store=gateway_settings_store,
                active_gateway_settings=active_gateway_settings,
                gateway_health_url=_gateway_health_url(configuration.gateway_url),
            )
            try:
                diagnostics_server.start()
            except OSError as exc:
                diagnostics_server = None
                app.logger.warning(
                    "Application 诊断页面启动失败，语音服务继续运行：%s",
                    exc,
                )
            else:
                app.logger.info(
                    "Application 诊断页面：%s/trace/",
                    diagnostics_server.base_url,
                )
        try:
            if configuration.gateway_url == DEFAULT_GATEWAY_URL:
                gateway_runtime = GatewayRuntimeManager.from_environment()
                diagnostics.set_status(
                    "gateway", "update", "正在检查固定版本 Qwen Gateway"
                )
                diagnostics.record(
                    "gateway.bootstrap_started",
                    detail="检查 qwen-audio-agent@1.10.2 私有运行时",
                    level="update",
                )
                try:
                    bootstrap_result = await asyncio.to_thread(
                        gateway_runtime.ensure_ready
                    )
                except GatewayBootstrapError as exc:
                    diagnostics.set_status("gateway", "error", str(exc))
                    diagnostics.record(
                        "gateway.bootstrap_failed",
                        detail=str(exc),
                        level="error",
                    )
                    raise RuntimeError(f"Qwen Gateway 初始化失败：{exc}") from exc
                diagnostics.record(
                    "gateway.bootstrap_ready",
                    detail=(
                        "复用已有本地 Gateway"
                        if bootstrap_result == "reused"
                        else "固定版本 Qwen Gateway 已启动"
                    ),
                )
                app.logger.info(
                    "Qwen Gateway 方案 B 初始化完成：%s",
                    bootstrap_result,
                )
            else:
                app.logger.info(
                    "使用 QWEN_AGENT_GATEWAY_URL 指定的外部 loopback Gateway，"
                    "跳过 Application 私有 Gateway 管理"
                )
            app.logger.info("启动 Qwen Audio Agent 半双工桥接")
            runtime = BridgeApplicationRuntime(
                app,
                configuration,
                diagnostics=diagnostics,
            )
            await runtime.run_forever()
        finally:
            diagnostics.set_status("application", "update", "Application 正在停止")
            if gateway_runtime is not None:
                await asyncio.to_thread(gateway_runtime.close)
            if diagnostics_server is not None:
                diagnostics_server.close()


if __name__ == "__main__":
    asyncio.run(main())
