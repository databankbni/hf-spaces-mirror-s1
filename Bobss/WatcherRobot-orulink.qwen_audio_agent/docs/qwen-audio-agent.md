# 配置 qwen-audio-agent

本 Application 不直接访问模型供应商。语音模型、Agent 后端和凭据都由本机
qwen-audio-agent Gateway 管理；Application 只连接 Gateway 的 loopback WebSocket。

推荐并已验证的框架版本为 `qwen-audio-agent@1.10.2`。以下命令以 Windows
PowerShell 为例，macOS/Linux 可使用等价 shell 命令。

## 1. 方案 B：Application 私有安装

Hugging Face 快照不复制外部 Gateway 源码。Application 自带
`runtime-dependencies.json`，固定声明 `qwen-audio-agent@1.10.2`、npm integrity、
Node/npm 版本和本机 health URL。默认首次运行会从正式源
`https://registry.npmjs.org/` 安装到 Application 私有
`runtime/qwen-gateway`，不会全局安装，也不会使用 `latest` 或任何 dist-tag。

准备 Node.js `^22.22.2`、`^24.15.0` 或 `>=26.0.0`，以及 npm `>=10`。默认开关：

```powershell
$env:QWEN_AGENT_GATEWAY_AUTO_INSTALL = "true"
$env:QWEN_AGENT_GATEWAY_AUTO_START = "true"
$env:QWEN_AGENT_NPM_REGISTRY = "https://registry.npmjs.org/"
```

如果默认私有目录不可写，可设置 `QWEN_AGENT_RUNTIME_DIR` 到当前用户可写目录。关闭
`QWEN_AGENT_GATEWAY_AUTO_INSTALL` 后，Application 只做预检并输出固定安装指令；
关闭 `QWEN_AGENT_GATEWAY_AUTO_START` 后，需由运维自行启动 Gateway。

高级/手工回退模式仍可全局安装：

```powershell
npm install --global qwen-audio-agent@1.10.2 --registry https://registry.npmjs.org/
qwenaudio --help
```

## 2. 创建 Gateway 配置

私有 CLI 位于
`runtime/qwen-gateway/node_modules/qwen-audio-agent/cli/bin/qwenaudio.mjs`。
首次配置可运行全局 `qwenaudio config`，或用当前 Node 执行该私有 CLI 并附加
`config` 参数。命令会输出并创建用户级 `config.env`。当前 Application 也可在 Trace
页面保存 API Key；它只写入被 Git 忽略的 `runtime/gateway-settings.json`，POSIX 权限
固定为 `0600`，读取 API 不返回明文。不要把 API Key 写入 `app.json` 或源码。

国内 DashScope 最小配置：

```dotenv
DASHSCOPE_API_KEY=sk-your-key
QWEN_AUDIO_REALTIME_MODEL=qwen-audio-3.0-realtime-plus
```

默认 Realtime 节点属于中国内地 DashScope。若使用百炼工作空间专属节点，可另外设置：

```dotenv
DASHSCOPE_WORKSPACE_ID=your-workspace-id
```

对应域名格式为
`https://<workspace-id>.cn-beijing.maas.aliyuncs.com`。本方案不要求阿里云国际站，
也不要配置 `dashscope-intl.aliyuncs.com`。如系统配置了 HTTP/HTTPS 代理，请确保
`127.0.0.1` 和本机 Gateway 进入 `NO_PROXY`；是否让云端请求使用代理由运行环境决定。

可选 Realtime 模型：

- `qwen-audio-3.0-realtime-plus`：默认，偏质量。
- `qwen-audio-3.0-realtime-flash`：偏低延迟和成本。
- `qwen3.5-omni-flash-realtime`：Omni Flash。
- `qwen3.5-omni-plus-realtime`：Omni Plus。

也可用 CLI 精确切换模型，随后重启 Gateway：

```powershell
qwenaudio config set --realtime-model qwen-audio-3.0-realtime-plus
qwenaudio gateway restart
```

## 3. 配置 Agent 后端

只需要语音聊天时不设置 `AGENT_PROTOCOL`，或设为 `none`。需要执行工具、文件操作
或后台任务时，选择一个已安装的 Agent。例如复用本机 Codex：

```dotenv
AGENT_PROTOCOL=codex
QWEN_AUDIO_AGENT_BACKEND_PERMISSION_MODE=native
# 可选；留空时复用 Codex 自身模型配置
QWEN_AUDIO_AGENT_BACKEND_MODEL=
```

检查并按需安装后端：

```powershell
qwenaudio setup --backend codex
qwenaudio install codex
```

也可以选择 `openclaw`、`opencode`、`qwen`、`qoder`、`kimi`、`hermes`、
`codebuddy`、`claude` 或实验性的 `deepseek`。Gateway 会复用所选 Agent 的用户级
认证、模型、工具、MCP 与 Skill。权限模式推荐保持 `native`；只有在可信工作区且
明确接受风险时才使用 `full`。

## 4. 启动并检查 Gateway

前台运行便于初次排障：

```powershell
qwenaudio gateway
```

需要常驻时可安装为用户服务：

```powershell
qwenaudio gateway install
qwenaudio gateway status
```

默认 HTTP 地址为 `http://127.0.0.1:3101`。Application 默认使用下列 WebSocket
地址，无需额外设置；显式设置时会进入“外部 loopback Gateway”模式并跳过私有
安装与启动：

```powershell
$env:QWEN_AGENT_GATEWAY_URL = "ws://127.0.0.1:3101/api/realtime?sessionId=watcherobot-main"
```

`sessionId` 必须非空，并建议为每台长期使用的机器人保持稳定。Application 只接受
loopback Gateway，不应把端口 3101 暴露到局域网。

## 5. 启动 WatcheRobot Application

通过 WatcheRobot SDK Daemon 运行，不要直接执行 `app.py`：

```powershell
watcherobot app run .\application
```

打开 `http://127.0.0.1:8768/trace/`，输入机器人显示的六位配对码。健康状态应依次
看到 Gateway 连接、Realtime ready、设备连接与 VAD ready。

## 排障

- `Gateway 未连接`：先运行 `qwenaudio gateway status`，检查端口 3101 和
  `QWEN_AGENT_GATEWAY_URL` 的 `sessionId`。
- `Realtime 鉴权失败`：检查 `DASHSCOPE_API_KEY` 是否由 Gateway 进程读取；修改
  `config.env` 后执行 `qwenaudio gateway restart`。
- 语音正常但 Agent 不执行：检查 `AGENT_PROTOCOL` 和 `qwenaudio setup --backend ...`；
  仅前台模式不会创建后台任务。
- 修改环境变量后不生效：重启 Gateway，再由 SDK 停止并重新启动 Application。
- 不要在诊断截图、日志或问题反馈中提交 API Key、完整带凭据 URL 或配对码。
