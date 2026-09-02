# 版本兼容与发布绑定

## Application 1.3.1

本页是 Hugging Face Application 快照的运行版本合同。Application 只包含 Python
源码，不包含 Daemon、Qwen Audio Agent Gateway 或 ESP32 镜像。

| 组件 | 版本绑定 | 说明 |
|---|---|---|
| Qwen Audio Agent Application | `1.3.1` | 本次 Hugging Face 源码快照 |
| WatcheRobot Python SDK | `watcherobot >=0.1.3,<0.2` | Manifest 强制范围 |
| 已验证 SDK 构建 | `0.1.3` / `c333bbf083edd5909edcddc60d840de115ecb1a2` | `v0.1.3` 发布提交，包含 Application 重启资源交接修复 |
| 最低 ESP32 固件 | `WatcheRobot ESP32-S3 v0.3.5` | 本 App 所需 Python SDK 音频和标准表情能力的最低发布基线 |
| 推荐 ESP32 固件 | `WatcheRobot ESP32-S3 v0.3.7` | 当前最新稳定发布基线，包含标准 `evt.sdk.input` 触摸事件 |
| Qwen Audio Agent Gateway | npm `qwen-audio-agent@1.10.2` | 由 Application 按固定 integrity 私有安装；不复制源码 |

Application does not bundle firmware and does not flash the robot. 安装 Application
不会改变设备固件；固件升级应继续使用 WatcheRobot 官方发布包和维护流程。

## 兼容性说明

- `v0.3.5` 是最低基线，不要求为本 App 添加任何专用固件改动。
- `v0.3.7` 是推荐部署版本；本 App 仍只调用标准 SDK Device channel、麦克风、播放和
  官方表情接口。
- 基础语音和表情仍兼容 `v0.3.5`；显式后背/屏幕触摸打断 Feature 要求 `v0.3.7`
  的标准 `evt.sdk.input` 上报以及 SDK `0.1.3` 的 `robot.inputs` API。本次不需要为
  该 Feature 修改或烧录自定义固件。
- SDK `0.1.3` 是本版本的硬性运行要求。旧 SDK 缺少已验证的重启资源交接行为，可能
  在 Application 重启后短暂或持续得到麦克风 `no_capacity`。
- `requires_watcherobot` 是安装门禁；精确 commit 是本次验证证据，不会由应用商店
  自动检出本机 Git revision。
- Qwen Audio Agent Gateway 的源码不进入 Application；`runtime-dependencies.json`
  固定版本后由 Application 从官方 npm 源安装到私有 runtime。DashScope 国内节点、
  API Key 和 Agent backend 仍由部署端配置，不写入发布包。
- `1.10.2` 使用 `watcherobot` dist-tag 发布以避免改写上游 `latest`；Application
  始终按精确版本安装，不依赖 dist-tag 解析。
- Gateway `v1.10.2` 已提供本 Application 使用的 `interrupt` 和手动
  `input.commit` 协议。Application `1.3.1` 的可移植版本严格使用正式 npm 包，
  不隐式混入仓库工作树补丁。
- `1.3.1` 修复诊断页配置重启链路：受管模式保留 SDK Daemon 与 Device channel，
  只重启 Gateway 和 Application；受控停机不再下发 disconnect 行为。该修复不要求
  修改或重新烧录 ESP32 固件。

## macOS 兼容门禁

| 项目 | 已验证基线 |
|---|---|
| 主机 | Apple Silicon arm64 / macOS 26.6.2 |
| Python | Python 3.10.19 / 3.11.15 / 3.12.12 |
| SDK wheel | `watcherobot 0.1.3` / `darwin-arm64` bundled runtime wheel |
| Node.js / npm | Node.js 22.22.2 / npm 10+ |
| Gateway | `qwen-audio-agent 1.10.2` / DashScope 中国内地节点 |

- 三个 Python 版本均能安装同一 SDK wheel，并通过 `watcherobot app check`。
- Gateway、Daemon、Application、Device WebSocket 与 Trace 分别在
  `3101`、`8767`、`8765`、`8768` 单实例监听；停止后端口全部释放。
- 连续 10 次 Application 重启产生 11 个唯一 Application PID 和 11 个唯一 Trace
  实例，每轮均恢复 Application/Gateway Ready，无僵尸进程或重复端口监听。
- 53 项 SDK 路由、生命周期与日志测试通过，覆盖无 Application 时透明转发、有
  Application 时业务帧先进入 Application、设备重连和管理 REST。
- Application 结构化日志和 Daemon 日志均可查询。日志问题不会通过增加业务消息
  旁路规避。
- Application 安装/升级与真机多轮语音、触摸打断仍属于发布前独立验收门禁；只有
  固定候选快照通过这些门禁后才能提交应用市场审核。

## 发布与验收记录

- Application 测试：完整 WatcheRobot 集成测试集通过。
- macOS 生命周期验收：连续 10 次 Application 重启均恢复 Ready；每轮四个本地端口
  维持单监听，停止后全部释放。
- 路由验收：53 项 SDK 路由、生命周期与日志测试通过。
- 真机验收：必须按 `operations.md` 另行保存脱敏证据；本节的主机门禁不替代真机
  对话和触摸打断验收。
- 固件改动：无；本次发布不修改、不打包、不烧录 ESP32。
- 触摸打断：后背 `press` 默认启用；屏幕 `tap` 可选；仅 PLAYING 生效，后台 Agent
  任务保持运行。

发布链接：

- [WatcheRobot ESP32-S3 v0.3.5](https://github.com/orulink-ai/WatcheRobot_esp32/releases/tag/v0.3.5)
- [WatcheRobot ESP32-S3 v0.3.7](https://github.com/orulink-ai/WatcheRobot_esp32/releases/tag/v0.3.7)
- [WatcheRobot Python SDK](https://github.com/orulink-ai/WatcheRobot_python_sdk)
