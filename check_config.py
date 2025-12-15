#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置检查脚本
用于检查 DiscuzSentinel 的配置是否正确
"""

import os

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

print("=" * 60)
print("DiscuzSentinel 配置检查")
print("=" * 60)

# 检查 Cookie
cookie = os.getenv('DISCUZ_COOKIE', 'your_cookie_here')
if not cookie or cookie == 'your_cookie_here':
    print("❌ Cookie 未配置")
    print("   请设置 DISCUZ_COOKIE 环境变量或编辑 .env 文件")
    print("   获取方法：浏览器 F12 -> Network -> 查看请求的 Cookie")
else:
    print(f"✅ Cookie 已配置（长度: {len(cookie)} 字符）")
    # 检查 Cookie 是否包含关键字段
    if 'saltkey' in cookie.lower() and 'auth' in cookie.lower():
        print("   ✅ Cookie 包含关键字段（saltkey, auth）")
    else:
        print("   ⚠️  Cookie 可能不完整，建议检查是否包含 saltkey 和 auth")

# 检查 FID
fids_str = os.getenv('DISCUZ_TARGET_FIDS', '147,148')
fids = [int(fid.strip()) for fid in fids_str.split(',') if fid.strip()]
if not fids:
    print("❌ 未配置监控驿站（DISCUZ_TARGET_FIDS）")
else:
    print(f"✅ 监控驿站已配置: {fids}")

# 检查 Webhook
dingtalk_webhook = os.getenv('DINGTALK_WEBHOOK', '')
feishu_webhook = os.getenv('FEISHU_WEBHOOK', '')
system_alert_webhook = os.getenv('SYSTEM_ALERT_WEBHOOK', '')

webhook_count = 0

if dingtalk_webhook and 'dingtalk' in dingtalk_webhook and 'YOUR_TOKEN' not in dingtalk_webhook:
    print("✅ 钉钉 Webhook 已配置")
    webhook_count += 1
else:
    print("⚠️  钉钉 Webhook 未配置或使用默认值")

if feishu_webhook and 'feishu' in feishu_webhook and 'YOUR_TOKEN' not in feishu_webhook:
    print("✅ 飞书 Webhook 已配置")
    webhook_count += 1
else:
    print("⚠️  飞书 Webhook 未配置或使用默认值")

if system_alert_webhook and 'YOUR_TOKEN' not in system_alert_webhook:
    print("✅ 系统告警 Webhook 已配置")
    webhook_count += 1

if webhook_count == 0:
    print("❌ 未配置任何 Webhook，Cookie 失效时将无法收到告警通知")
    print("   建议至少配置一个 Webhook（DINGTALK_WEBHOOK 或 FEISHU_WEBHOOK）")

# 检查 .env 文件
if os.path.exists('.env'):
    print("✅ .env 文件存在")
else:
    print("⚠️  .env 文件不存在")
    print("   建议运行：cp env.example .env")

print("=" * 60)
print("检查完成")
print("=" * 60)

