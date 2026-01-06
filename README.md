# DiscuzSentinel - Discuz论坛多驿站监控系统

## 功能特性

- 监控多个Discuz论坛板块(FID)的新帖
- 支持FID到不同Webhook的映射配置
- 全局图片上传配置，所有图片使用同一AppID/Secret上传
- 支持钉钉和飞书Webhook推送
- 自动图片上传和原生显示
- 智能URL清洗，避免误删动态图片链接
- 图片格式自动识别，确保飞书上传成功

## 最新修复 (2026-01-06)

### 修复内容

**问题**：飞书图片上传报错 "Can't recognize image format."

**根本原因**：
1. URL清洗逻辑过于简单粗暴，把 `forum.php?mod=image&aid=...` 截断成 `forum.php`，导致下载到论坛首页HTML而不是图片
2. HTML片段中图片src结尾带有奇怪的 `>` 符号未清洗
3. 飞书上传时文件名扩展名与实际图片格式不匹配

**修复方案**：
1. **智能URL清洗**：只对非Discuz动态链接去除`?`参数，保留`forum.php`和`mod=image`的参数
2. **去除异常符号**：自动清理URL末尾的`>`符号
3. **格式自动识别**：根据图片二进制头自动设置正确的文件扩展名(.png/.jpg/.gif等)
4. **HTML内容校验**：上传前检查下载内容是否为HTML页面，避免误传

### 配置说明

项目已从`.env`格式改为`config.json`格式，更便于管理和扩展。

```bash
# 复制配置模板
cp env.example config.json
```

### 配置结构

```json
{
  "discuz": {
    "target_fids": "147,148",           // 要监控的FID列表，用逗号分隔
    "cookie": "your_cookie_here",       // 论坛Cookie
    "base_url": "https://www.55188.com" // 论坛基础URL
  },
  "image_upload": {
    "app_id": "",                       // 全局图片上传AppID
    "app_secret": "",                   // 全局图片上传Secret
    "upload_url": "http://frp-cup.com:12245/upload/upload.html" // 图床URL
  },
  "notifications": {
    "fid_mappings": {                   // FID到Webhook的映射
      "147": {
        "webhook_url": "",              // Webhook地址
        "webhook_type": "dingtalk",     // 类型：dingtalk 或 feishu
        "secret": ""                    // Webhook签名密钥（可选）
      },
      "148": {
        "webhook_url": "",
        "webhook_type": "feishu",
        "secret": ""
      }
    }
  },
  "system": {
    "preview_limit": 4000,              // 文本预览长度
    "log_file": "discuz_sentinel.log",  // 日志文件
    "log_level": "INFO",                // 日志级别
    "log_retention_days": 7,            // 日志保留天数
    "state_file": "monitor_state.json"  // 监控状态文件
  }
}
```

### URL清洗逻辑说明

修复后的URL清洗逻辑能够正确处理以下情况：

- ✅ `forum.php?mod=image&aid=123&w=500` → 保留参数（Discuz动态图片链接）
- ✅ `image.jpg?imageMogr2/thumbnail/800x` → 去除参数（静态图片链接）
- ✅ `image.png>` → 去除末尾`>`符号
- ✅ `smile.gif` → 无参数无需处理

## 使用方法

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行程序

```bash
python discuz_sentinel.py
```

### 查看日志

```bash
tail -f discuz_sentinel.log
```

## 故障排除

1. **Cookie失效**：检查日志中的"Cookie可能已失效"提示
2. **图片上传失败**：检查全局AppID/Secret和图床地址
3. **Can't recognize image format**：检查是否为最新修复版本
4. **FID无配置**：确保所有要监控的FID都在`fid_mappings`中配置了对应的Webhook

## 重要提醒

- **安全提醒**：不要将`config.json`文件提交到Git仓库
- **Cookie获取**：从浏览器开发者工具的Network标签页获取
- **Webhook配置**：确保Webhook地址正确且有发送权限
- **图片上传**：配置全局AppID/Secret后，所有图片都会使用此配置上传
