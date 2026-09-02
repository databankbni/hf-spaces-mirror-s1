# 配置参数

所有配置通过环境变量注入。URL 可能包含凭据或会话标识，日志不会输出完整 URL、
音频内容或完整 Gateway 消息。

## Gateway

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_AGENT_GATEWAY_URL` | `ws://127.0.0.1:3101/api/realtime?sessionId=watcherobot-main` | 仅接受 loopback、`/api/realtime` 和非空 `sessionId`；改为其他 loopback URL 后跳过私有 Gateway 管理 |
| `QWEN_AGENT_GATEWAY_AUTO_INSTALL` | `true` | 默认 URL 不健康且私有固定版本缺失时，从正式 npm 源安装 |
| `QWEN_AGENT_GATEWAY_AUTO_START` | `true` | 默认 URL 不健康时启动 Application 私有 Gateway |
| `QWEN_AGENT_RUNTIME_DIR` | Application `runtime/qwen-gateway` | 私有 npm prefix；必须是当前用户可写目录 |
| `QWEN_AGENT_NPM_REGISTRY` | `https://registry.npmjs.org/` | 固定正式 npm registry；拒绝其他值，避免依赖漂移 |
| `QWEN_AGENT_GATEWAY_SETTINGS_FILE` | Application `runtime/gateway-settings.json` | Trace 页面保存的私有 Gateway/Agent 配置；POSIX 权限固定为 `0600` |
| `QWEN_AGENT_PROVIDER` | `dashscope` | 实时语音 Provider |
| `QWEN_AGENT_CLIENT_LABEL` | `WatcheRobot` | Gateway 中显示的客户端标签 |
| `QWEN_AGENT_TAKEOVER` | `true` | 是否接管同一会话的旧语音客户端 |
| `QWEN_AGENT_CONNECT_TIMEOUT_SECONDS` | `15` | Gateway 连接超时 |
| `QWEN_AGENT_RESPONSE_START_TIMEOUT_SECONDS` | `15` | 显式提交后等待首个模型响应的超时；超时会重建 Realtime 会话 |
| `QWEN_AGENT_RESPONSE_TIMEOUT_SECONDS` | `90` | 单轮回复与设备播放超时 |
| `QWEN_AGENT_MAX_RESPONSE_BYTES` | `2097152` | 单次回复上限，范围 2 B～4 MiB |
| `QWEN_AGENT_WAKE_WORD_ENABLED` | `false` | 休眠时将机器人 PCM 仅送入 Gateway 本地 KWS，命中后恢复 VAD 对话 |

推荐 Gateway 使用个人身份模式并只监听本机：

```powershell
$env:QWEN_AUDIO_AGENT_IDENTITY_MODE = "personal"
$env:HOST = "127.0.0.1"
$env:QWEN_AUDIO_WAKE_WORD_ENABLED = "true"
$env:QWEN_AUDIO_WAKE_WORD = "watcher"
$env:QWEN_AUDIO_WAKE_WORD_TOKENS = "W AA1 CH ER0"
```

`browser` 身份模式需要 Gateway 签发的网页登录 Cookie，本硬件 Application 不
代管浏览器身份，因此不属于当前真机验收配置。

Trace 页面的“Gateway 与 Agent”面板可管理 `DASHSCOPE_API_KEY`、
`QWEN_AUDIO_REALTIME_MODEL`、`AGENT_PROTOCOL`、后台模型、权限模式和进程归属；
OpenClaw 外部模式还可管理服务地址与独立令牌。保存值优先于启动进程继承的同名
环境变量。API Key 和令牌只写入上述私有文件，读取接口仅返回“是否已配置”，不会
回传明文。切换配置后必须重启完整服务链路，以保证 Gateway、后台 Agent 与
Application 使用同一份配置。

## VAD

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_AGENT_VAD_ENABLED` | `true` | 自动 VAD；关闭后使用设备/桌面手动触发 |
| `QWEN_AGENT_VAD_START_RMS` | `600` | 开始说话 RMS 阈值 |
| `QWEN_AGENT_VAD_STOP_RMS` | `350` | 结束阈值，不得高于开始阈值 |
| `QWEN_AGENT_VAD_START_FRAMES` | `3` | 开始所需连续高能量帧数 |
| `QWEN_AGENT_VAD_SILENCE_MS` | `1000` | 结束所需连续静音时长 |
| `QWEN_AGENT_VAD_PRE_ROLL_MS` | `300` | 触发前保留音频，避免吞掉首字 |
| `QWEN_AGENT_VAD_MAX_UTTERANCE_MS` | `60000` | 单轮最长录音时长 |
| `QWEN_AGENT_VAD_SETTINGS_FILE` | Application `runtime/vad-settings.json` | Trace 页面保存的 VAD 配置文件；可改为本机绝对路径 |

默认阈值针对当前设备静音约 60～100 RMS 的环境。换用不同麦克风或现场噪声
明显变化时，应重新采样底噪并校准阈值。Trace 页面可以读取、校验、保存和恢复
这些参数；保存后需要使用页面按钮重启服务才会加载新配置。配置文件
属于本机运行数据，不进入 Git 或 Application 发布快照。

## 显式触摸打断

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_AGENT_TOUCH_INTERRUPT_ENABLED` | `true` | 启用设备播放阶段的显式触摸打断 |
| `QWEN_AGENT_TOUCH_INTERRUPT_SOURCES` | `back_touch` | 允许来源，支持 `back_touch`、`screen_touch` 或两者逗号分隔 |
| `QWEN_AGENT_TOUCH_INTERRUPT_DEBOUNCE_MS` | `500` | 接受触摸后的防抖窗口，范围 100～3000 ms |
| `QWEN_AGENT_TOUCH_INTERRUPT_SETTINGS_FILE` | Application `runtime/touch-interrupt-settings.json` | Trace 页面保存的触摸打断配置文件 |

默认只接受后背触摸 `press`。屏幕任意位置 `tap` 必须在 Trace 页面或环境变量中
显式启用。无论来源如何，只有对话状态为 `PLAYING`、即设备扬声器已经实际开始播放
时才会打断；其余状态只记录 `interrupt.ignored`，不会开始或终止 Agent 任务。
保存配置后需要重启服务才会生效。

## Application 诊断页

| 变量 | 默认值 | 说明 |
|---|---|---|
| `QWEN_AGENT_DIAGNOSTICS_ENABLED` | `true` | 启用 Application 自有 trace/status 页面 |
| `QWEN_AGENT_DIAGNOSTICS_PORT` | `8768` | 本机诊断端口，范围 1024～65535 |
| `QWEN_AGENT_DAEMON_CONTROL_URL` | `http://127.0.0.1:8767` | 页面使用的 SDK Daemon 管理 REST origin |

诊断服务固定绑定 `127.0.0.1`，不能配置成局域网地址。它只暴露 Application 内部
的有界结构化事件，也不记录音频和转写内容。Gateway 管理 API 对密钥脱敏，并拒绝
非 loopback Host 与跨源写请求。页面中的配对操作由浏览器直接调用
上述 loopback SDK Daemon 地址；只接受无凭据的 HTTP loopback origin。页面的
“重启应用服务”操作在开发集成模式下原子写入请求，由 Application 进程树之外的
受管 supervisor 保留 SDK Daemon 和 Device channel，只重启 Gateway 与当前
Application；独立发布模式则通过 SDK Daemon 官方管理 REST 重启当前 Application，由 Application 同步重建其
私有 Gateway。
