# 架构与数据链路

## 运行边界

Qwen Audio Agent 是受 SDK Daemon 管理的 Application：

```text
ESP32 Device channel
        |
        v
WatcheRobot SDK Daemon
        |
        v
Qwen Audio Agent Application
        |
        v
Qwen Audio Agent Gateway (127.0.0.1)
        |
        +-- DashScope Realtime（语音识别与生成）
        +-- Agent backend（例如本地 Codex ACP）
```

Daemon 只管理连接和透明路由，不解析语音业务内容。Application 通过
`ApplicationContext` 使用授权的 Desktop/Device channel，不持有配对凭据，也不
建立第二条设备连接。

## 模块职责

| 模块 | 职责 |
|---|---|
| `app.py` | 固定 SDK Application 入口和依赖装配 |
| `configuration.py` | 环境变量解析、默认值与边界校验 |
| `runtime.py` | Gateway 重连、Desktop 投影和生命周期编排 |
| `service.py` | 单轮半双工采集、生成、播放和资源清理 |
| `vad.py` | 本地 RMS 阈值 VAD 与 pre-roll |
| `behavior_system.py` | Application 自有的状态协调器，通过标准 SDK Animation 渲染官方表情 |
| `gateway_client.py` | Gateway WebSocket 会话和发送背压边界 |
| `protocol.py` | Gateway 消息及音频格式校验 |
| `audio_buffer.py` | 按 `responseId` 有界缓冲下行音频 |
| `conversation.py` | 对话轮次状态转换 |
| `triggers.py` | 设备与 Desktop 输入触发处理 |
| `desktop_events.py` | Gateway 事件到 Desktop channel 的安全投影 |
| `diagnostics.py` | Application 自有的有界 trace、脱敏 Gateway health、配置 API 和 loopback HTTP 服务 |
| `settings.py` | 本地 Gateway/Agent、VAD、触摸打断参数校验、原子持久化和启动时环境注入 |
| `service_restart.py` | 向外部生命周期 supervisor 原子提交重启请求；独立模式回退到 Daemon Application 重启 |
| `static/` | 独立 trace/status 与 Gateway/Agent 管理页面，通过 Daemon 官方 REST 发起设备管理 |

## 音频链路

上行合同为单声道 PCM16、16 kHz。Application 自动打开 PCM 监测，本地 VAD
只保留有界 pre-roll；检测到说话后才开始上传，连续静音后关闭设备录音资源，
随后向 Gateway 显式发送 `input.commit`。Gateway 为该客户端建立 DashScope
push-to-talk 会话（`turn_detection=null`），严格按
`input_audio_buffer.commit -> response.create` 提交一轮，不再叠加 Realtime
`smart_turn` 做第二次断句。

提交后 15 秒内未收到 `response.started` 时，Application 将当前轮次标记为
`response.timeout` 并结束 Gateway 会话。统一重连会清空供应商输入缓冲、释放设备
麦克风并重新进入 VAD，避免失败轮次污染下一轮。

下行合同为单声道 PCM16、24 kHz。Application 按 `responseId` 完整缓冲回复，
完成格式、大小和边界校验后一次性交给 SDK 播放。播放期间不录音，也不执行
自然语音打断。

显式触摸打断是独立的设备输入链路：

```text
ESP32 evt.sdk.input
  -> SDK Daemon 透明路由
  -> Application robot.inputs
  -> 仅 ConversationState.PLAYING 接受
  -> 停止 SDK 扬声器并清理当前 responseId
  -> Gateway {"type":"interrupt"} / Provider response.cancel
  -> READY / awake_idle
```

后背 `press` 默认启用，屏幕 `tap` 默认关闭。输入循环与 Python VAD 并行运行，
因此 VAD 开启时仍能消费触摸事件。该操作只取消当前前台生成和播放，不调用 Agent
任务取消接口，后台 Agent/Codex 任务继续运行并可产生后续终态事件。

## 机器人状态反馈

机器人使用 ESP32-S3 `v0.3.5` 已有的官方 Behavior/Animation 资源表达 Application
状态；日常 `READY` 使用标准 `awake_idle` Behavior，而不是固定 `standby1`。
不依赖 `service.status.v1` 或定制固件。`READY` 必须同时满足 Gateway ready 和
设备麦克风进入 VAD monitoring；短暂故障先进入 `RECOVERING`，15 秒未恢复才进入
`ERROR`。完整状态、资源和音频安全规则见
[表情行为状态机](behavior-state-machine.md)。

## Desktop channel

Application 将 `voice.*`、轮次、转写、响应状态和 `task.*` 投影到 Desktop channel，
供桌面展示任务和权限请求。`audio.delta` 不发送给桌面，Application 也不会自动
批准 Agent 权限。

## 管理面与诊断面

Daemon REST 负责配对、设备连接和 Application 生命周期等管理能力。语音轮次、
Gateway、Agent 和设备播放状态由 Application 在独立的 `127.0.0.1:8768` 页面
展示。为方便真机测试，该页面直接调用 loopback Daemon REST 完成配对、取消和
断开。页面还可写入当前 Application 私有的 Gateway/Agent、VAD 和触摸配置；敏感值
只保存到 `0600` 运行时文件，GET 接口不返回明文。开发集成模式由 Application
进程树之外的生命周期 supervisor 保留 SDK Daemon 与设备链路，只重建 Gateway 和 Application；独立
发布模式通过 Daemon 官方接口重启 Application 及其私有 Gateway。页面不复制
Gateway 或 Daemon 业务实现，也不持有设备会话。诊断页停止或端口占用不会中断
语音主链路。
