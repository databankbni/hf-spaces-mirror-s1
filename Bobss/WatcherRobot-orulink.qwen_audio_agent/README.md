---
title: "Qwen Audio Agent"
sdk: static
---

# Qwen Audio Agent

A half-duplex voice conversation Application that connects WatcheRobot to a
local Qwen Audio Agent Gateway. It provides automatic VAD, audio upload,
response buffering, device playback, visible robot behavior states, and an
explicit touch-to-interrupt path. Natural voice interruption remains out of
scope.

- Application ID: `orulink.qwen_audio_agent`
- Version: `1.3.1`
- Author: Orulink AI
- WatcheRobot SDK: `>=0.1.3,<0.2`
- Validated SDK build: `0.1.3` at commit
  `c333bbf083edd5909edcddc60d840de115ecb1a2`
- Minimum firmware baseline: WatcheRobot ESP32-S3 `v0.3.5`
- **Recommended firmware: WatcheRobot ESP32-S3 `v0.3.7`**. This is the
  validated baseline for touch interruption, device behavior states, and the
  current voice path. Firmware `v0.3.5` only satisfies the minimum connection
  baseline.
- Explicit touch interrupt: ESP32-S3 `v0.3.7` plus SDK `0.1.3`; rear-touch
  `press` enabled by default, screen `tap` opt-in
- Supported host platforms: Windows and macOS
- Python dependency: `websockets>=14,<16`
- Managed Gateway dependency: `qwen-audio-agent@1.10.2` from the official npm
  registry, installed into an Application-private runtime directory
- Behavior design: [Behavior State Machine](docs/behavior-state-machine.md)

## Architecture

The device data path is fixed:

```text
ESP32 <-> SDK Daemon <-> Qwen Audio Agent Application <-> Local Gateway
```

The Application obtains the Daemon-injected Desktop and Device channels through
`ApplicationContext.from_environment()`. It does not scan for devices or open a
second device WebSocket. Desktop microphone commands are handled by the active
Application and never bypass it through the Daemon.

Uplink audio uses `16 kHz / mono / PCM16`; downlink audio uses
`24 kHz / mono / PCM16`. See [Architecture and Data Flow](docs/architecture.md)
for component boundaries.

## First run: managed Gateway (Plan B)

The Hugging Face snapshot does not copy the Qwen Audio Agent or WatcheRobot SDK
source trees. Instead it contains `runtime-dependencies.json`, which pins
`qwen-audio-agent@1.10.2` and its npm integrity. On the default loopback URL,
the Application checks Node/npm, installs that exact package from
`https://registry.npmjs.org/` into its private `runtime/qwen-gateway` directory,
reuses an already healthy Gateway, or starts the private CLI. It never installs
the package globally and never selects `latest`.

Install Node.js `^22.22.2`, `^24.15.0`, or `>=26.0.0` with npm `>=10` before the
first run. The DashScope API key, China endpoint, model, and Agent backend still
belong to the Gateway user configuration and are never stored in this
Application. Run `qwenaudio config` once to create that user configuration; see
the setup guide for the private CLI path and fallback commands.

The validated Gateway baseline is `qwen-audio-agent v1.10.2`. See
[Qwen Audio Agent Configuration](docs/qwen-audio-agent.md) for installation,
DashScope configuration, model selection, Agent backend setup, and connectivity
checks.

The Hugging Face snapshot contains the Python Application, the fixed dependency
contract, and bootstrap logic. Gateway source is not embedded. Application
`1.3.1` uses the official `qwen-audio-agent@1.10.2` npm package; repository-only
Gateway patches are not part of this portable release.

Version `1.3.1` fixes managed configuration restarts: the diagnostics page now
keeps the SDK Daemon and Device channel alive while restarting only the Gateway
and Application. A controlled Application stop also avoids rendering the
disconnect behavior, so an already paired robot does not loop a disconnect
animation or require a new pairing code after a routine settings restart.

The default Gateway URL is already configured. These overrides are optional:

```powershell
$env:QWEN_AGENT_GATEWAY_URL = "ws://127.0.0.1:3101/api/realtime?sessionId=watcherobot-main"
$env:QWEN_AGENT_GATEWAY_AUTO_INSTALL = "true"
$env:QWEN_AGENT_GATEWAY_AUTO_START = "true"
$env:QWEN_AGENT_WAKE_WORD_ENABLED = "false"
```

See [Configuration](docs/configuration.md) for all supported environment
variables. PC-side wake-word detection is optional and disabled by default.

## Development

From the independent repository's `integrations/watcherobot` directory, run:

```powershell
watcherobot app check .\application
watcherobot app run .\application
```

The Application must run through the SDK Daemon; do not execute `app.py`
directly. The Daemon owns device pairing, connectivity, Application lifecycle,
and runtime logs.

After startup, open `http://127.0.0.1:8768/trace/` to inspect conversation,
Gateway, Agent, device audio, and behavior states. The page also accepts the
six-digit device pairing code. Pairing and disconnection requests are delegated
to the SDK Daemon management API; the Application does not store pairing codes.
The Gateway and Agent panel securely persists the DashScope credential,
Realtime model, backend selection, permission mode, ownership, and supported
external connection settings. Secret values are never returned by the
diagnostics API. Saving and restarting recreates the complete managed stack in
the development integration, or restarts this Application and its private
Gateway in an installed runtime. The VAD and touch-interrupt panels persist
their own validated profiles and use the same restart action. Touch interruption
is accepted only after device playback has actually entered `PLAYING`; it
cancels the foreground response and speaker output while preserving background
Agent tasks.

## Publishing

```powershell
watcherobot app login
watcherobot app check .\application
watcherobot app publish .\application
watcherobot app submit .\application --commit <publish-returned-40-character-commit>
```

`publish` creates an immutable source snapshot in a public Hugging Face Space.
`submit` sends that exact commit to the official WatcheRobot marketplace for
review. Complete the automated and on-device checks in
[Operations and Acceptance](docs/operations.md) before submission.

This Application snapshot contains Python source only. It does not bundle or
flash ESP32 firmware. See the exact SDK and firmware release relationship in
[Compatibility and Release Binding](docs/compatibility.md).

## Documentation

- [Architecture and Data Flow](docs/architecture.md)
- [Compatibility and Release Binding](docs/compatibility.md)
- [Behavior State Machine](docs/behavior-state-machine.md)
- [Qwen Audio Agent Configuration](docs/qwen-audio-agent.md)
- [Configuration Reference](docs/configuration.md)
- [Operations, Acceptance, and Troubleshooting](docs/operations.md)
