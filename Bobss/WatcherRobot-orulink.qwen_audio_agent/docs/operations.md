# 运行、验收与故障处理

## 本地校验

从独立仓库的 `integrations/watcherobot` 目录执行：

```powershell
watcherobot app check .\application
python -m pytest tests\test_qwen_agent_application_package.py `
  tests\test_qwen_agent_audio_buffer.py `
  tests\test_qwen_agent_behavior_system.py `
  tests\test_qwen_agent_bridge_service.py `
  tests\test_qwen_agent_configuration.py `
  tests\test_qwen_agent_conversation_state.py `
  tests\test_qwen_agent_desktop_events.py `
  tests\test_qwen_agent_diagnostics.py `
  tests\test_qwen_agent_end_to_end.py `
  tests\test_qwen_agent_gateway_client.py `
  tests\test_qwen_agent_protocol.py `
  tests\test_qwen_agent_runtime.py `
  tests\test_qwen_agent_triggers.py `
  tests\test_qwen_agent_vad.py
```

## 真机验收

1. 确认 Node/npm 满足版本要求，并完成一次 `qwenaudio config`；Application 默认会
   私有安装并启动固定 `qwen-audio-agent@1.10.2`。也可提前启动已有 loopback Gateway。
2. 启动支持双模式配对的 SDK Daemon，在诊断页输入六位配对码；页面按 Python
   SDK 合同提交 `target_mode=python_sdk`。
3. 使用 `watcherobot app run` 启动本 Application。
4. 确认设备上线后自动进入 VAD 监听状态。
5. 播放 `tmp\test_voice.m4a` 或现场说话，至少完成一轮正常语音对话。
6. 核对表情状态至少经过 `READY -> LISTENING -> THINKING -> SPEAKING -> SUCCESS`
   并回到 `READY`；涉及工具时还应出现 `AGENT_WORKING`。
7. 核对每轮均包含录音、上行结束、回复生成、下发设备和播放完成事件。
8. 补测静音无上传、Gateway 断线重连和连续多轮对话。
9. 让设备播放一段足够长的回复，在 `SPEAKING/PLAYING` 时按一下后背；确认扬声器
   立即停止、表情回到 `awake_idle`，Trace 依次出现 `interrupt.accepted`、
   `device.playback.stopped`、`gateway.interrupt_sent` 和 `conversation.ready`。
10. 对后背与已启用的屏幕入口合计至少执行 5 次播放中打断，并确认非播放状态的
    同类单击不会停止 VAD、不会打开第二个麦克风，也不会产生 Gateway interrupt。
11. 打断后立即开始下一轮语音，确认 VAD 正常恢复；如果前一轮包含长 Agent 任务，
    确认任务仍继续运行。需要验证屏幕时，在页面启用 `screen_touch`、重启
    Application，再于播放阶段单击屏幕。

Application 运行后在浏览器打开 `http://127.0.0.1:8768/trace/`。这里可以输入
配对码、取消连接、断开设备并观察当前 Application 的 trace 与状态。所有设备管理
动作仍由 SDK Daemon REST 执行。VAD 和触摸打断面板保存参数后，可以调用 Daemon 官方
`/daemon/application/stop` 和 `/daemon/application/start` 管理接口重启当前
Application；页面不复制生命周期逻辑，也不会重启 Daemon、Gateway 或建立额外的
设备会话。

## 故障行为

- Gateway 断开时立即关闭麦克风、停止未完成播放并清空缓冲，以 1～30 秒指数
  退避重连。
- 最长录音、Gateway 发送、录音收尾和设备播放均有超时边界。
- Python VAD 结束后使用 push-to-talk 显式提交；15 秒内没有首响应则记录
  `response.timeout`，重建 Realtime 会话并自动恢复 VAD。
- 音频格式、采样率、`responseId` 或回复大小不符合合同时，当前 Gateway 会话
  会被终止并执行统一资源清理。
- 已完成、已取消或 Provider 重连前的 `responseId` 会进入有界 tombstone，避免
  陈旧或重复回复恢复播放。
- 播放开始、结束和取消分别上报 `playback.started`、`playback.ended` 和
  `playback.cancelled`。
- Desktop 慢消费者由有界异步队列隔离，不阻塞 Gateway 语音事件。
- `task.progress` 在 Desktop、Application 日志和 trace 入口统一按任务节流，避免
  Agent 高频增量事件挤掉同轮 ASR、TTS 和设备播放证据；终态事件不节流。
- Application 不调用 `robot.service.set_status()`，避免设备服务状态 UI 在租约变化或
  重连后重新抢占表情动画 surface。服务健康只在独立 Trace 页面展示。
- Agent 执行期间出现的中间语音会正常播放，但不会提前结束当前 trace 轮次或重新
  打开麦克风；只有 Agent 终态后的最终语音完成才结束本轮。
- 触摸打断只在设备实际播放时生效；停止扬声器、当前回复与 Provider 生成后立即
  释放语音轮次，后台 Agent task ID 不会被移除或取消。

## 常见检查

- 无法启动：先运行 `watcherobot app check`，确认 SDK 版本和 Python dependency。
- 设备不录音：确认设备为 `connected`，Application 正在运行，Gateway 已发送
  `voice.ready`。
- 有识别无语音：检查回复是否通过音频格式/大小校验，以及设备播放是否返回完成。
- 页面显示表情已切换但屏幕未播放：新版 Application 会等待动画 Job 进入
  `running/completed` 后才记录成功；检查 `behavior.render_failed` 的 Job ID、
  状态与错误原因，而不是只看命令 ACK。
- 表情命令统一返回 `invalid_state`：检查是否有其他客户端调用
  `robot.service.set_status()` 抢占动画 surface；本 Application 不发送该命令。
- 上行后长期停在“等待模型回复”：检查同轮是否先后出现
  `capture.upload_finished`、`realtime.turn_started` 和 `response.started`。缺少
  `realtime.turn_started` 表示 Gateway 未接受显式提交；缺少 `response.started`
  会在 15 秒后记录 `response.timeout` 并自动重连。
- 出现 `realtime.transcript_discarded`：供应商判定本轮没有有效转写；页面只记录
  丢弃原因，不保存音频或转写文本。
- 断线后不恢复：检查 Gateway 重连日志、麦克风资源是否释放，以及下一轮 VAD 是否
  重新进入监听。
- 触摸无效：确认固件为 `v0.3.7`、SDK 为 `0.1.3`，并检查 Trace 中是否出现
  `input.touch.received`。出现 `interrupt.ignored state_*` 代表触摸发生时设备尚未
  进入实际播放；`source_disabled` 代表来源未在页面启用。

## SDK 生命周期与发布绑定

Application `1.3.1` 要求 `watcherobot >=0.1.3,<0.2`。本次发布使用 SDK
`0.1.3`、发布提交 `c333bbf083edd5909edcddc60d840de115ecb1a2` 完成 macOS
生命周期与路由验证；真机语音和触摸打断仍必须按本页单独验收。
该 SDK 在替代进程启动前为旧 Device channel 保留排空窗口；Application 同时在
退出时限内释放媒体资源，并对短暂的 `no_capacity` 使用有界指数退避。

正式 PyPI 当前稳定版可能暂未包含该生命周期修复，因此部署本版本前应确认实际
`watcherobot --version` 为 `0.1.3`，并使用对应发行包或上述验证提交构建。不要通过
Application 直连设备、复制 Daemon 或增加麦克风消息旁路来规避版本要求。

固件最低兼容基线为 ESP32-S3 `v0.3.5`；推荐使用已验证的 `v0.3.7`。固件不包含在
Application Space 中，也不会由 Application 安装流程自动烧录。完整关系见
[版本兼容与发布绑定](compatibility.md)。
Hugging Face 发布物只包含 `application/`，其中新增固定依赖合同与 bootstrap，
但不包含 Gateway 源码或 API Key。默认运行时从正式 npm 源获取精确
`qwen-audio-agent@1.10.2`；离线部署需要事先准备同版本私有 npm 目录，或关闭自动
安装并由运维启动兼容的 loopback Gateway。
