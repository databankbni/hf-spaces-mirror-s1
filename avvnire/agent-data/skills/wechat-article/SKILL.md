---
name: wechat-article
description: 微信公众号推文自动生成技能
trigger: 每天定时生成天秤座运势/养生推文并上传微信草稿箱
---

# 微信公众号推文生成

## 流程
1. 调用 `/app/wechat_auto.py` 生成推文
2. 推文内容包括：标题、正文、配图
3. 上传到微信公众号草稿箱
4. 通过 notify_session.py 写入通知

## 定时
- Space 内部 cron 线程每天 07:00 自动触发
- 无需外部依赖
