---
title: TaoSync
emoji: 📦
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# TaoSync（原版）

基于 [AList V3](https://github.com/alist-org/alist) 的网盘自动同步工具（**原版**，非衍生版本）。
镜像来自官方 `dr34m/tao-sync`，项目主页：<https://github.com/Yijian0707/taosync>。

本 Space 只改了 `Dockerfile`（FROM 官方镜像 + 适配端口/持久化）和这个 `README`，**无需放任何源码**，
容器启动后监听 `$PORT`（默认 7860），打开 Space 页面即是 TaoSync 管理界面。

## 使用

1. 打开 Space 页面（TaoSync 管理界面）。
2. 按官方文档配置 AList / OpenList 连接与同步任务。
3. 配置与任务数据持久化在 Space 的 `/data`，重启不丢。

## 注意事项

- **必须开启联网**：Space 的 **Settings → 勾选 "Internet access"**，否则容器无法访问你的网盘 / OpenList。
- 首次启动的管理员密码会在容器日志里输出（HF 的 Space 日志可见），按官方说明登录即可。
- 原版由作者维护，具体功能/配置以官方文档为准；本仓库仅提供抱脸部署所需的 Dockerfile 封装。
