#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DiscuzSentinel - Discuz! 论坛多驿站监控系统
【飞书原生图适配版】
1. 钉钉：使用 Catbox/CF 外链直接显示
2. 飞书：自动将图片上传到飞书服务器 (需配置 AppID)，实现原生大图显示
"""

import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import urllib.parse
import hmac
import hashlib
import base64
import requests
from bs4 import BeautifulSoup

# 尝试加载 python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==================== 配置区域 ====================

# 目标驿站 FID 列表
TARGET_FIDS_STR = os.getenv('DISCUZ_TARGET_FIDS', '147,148')
TARGET_FIDS = [int(fid.strip()) for fid in TARGET_FIDS_STR.split(',') if fid.strip()]

# Cookie
COOKIE = os.getenv('DISCUZ_COOKIE', 'your_cookie_here')

# 钉钉配置
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
DINGTALK_SECRET = os.getenv('DINGTALK_SECRET', '')

# 飞书配置 (Webhook 必须填)
FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK', '')

# 飞书 App 配置 (★ 填入这两项才能直接显示图片 ★)
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')      # 例如: cli_a4d9...
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '') # 例如: 8F3...

# ==================== 新增这一行 ====================
# 飞书接收目标的 ID (chat_id, user_id 等，通常以 oc_ 或 ou_ 开头)
FEISHU_TARGET_ID = os.getenv('FEISHU_TARGET_ID', '')
# ====================================================

# 您的图床 (Cloudflare Pages)
ZYCS_IMG_HOST = os.getenv('ZYCS_IMG_HOST', 'https://zycs-img-4sd.pages.dev')

# 基础配置
PREVIEW_LIMIT = int(os.getenv('PREVIEW_LIMIT', '4000'))
BASE_URL = "https://www.55188.com"
STATE_FILE = "monitor_state.json"
LOG_FILE = os.getenv('LOG_FILE', 'discuz_sentinel.log')
LOG_LEVEL = logging.INFO
LOG_RETENTION_DAYS = 7

class DiscuzSentinel:
    def __init__(self):
        self.logger = logging.getLogger("DiscuzSentinel")
        self.logger.setLevel(LOG_LEVEL)
        self._setup_logging()
        self.session = requests.Session()
        self.state = self._load_state()
        self._setup_session()
        # 飞书 Token 缓存
        self.feishu_token = ""
        self.feishu_token_expire = 0.0
        self._check_config()

    def _setup_logging(self):
        handlers = [logging.StreamHandler()]
        if LOG_FILE:
            file_handler = TimedRotatingFileHandler(
                LOG_FILE, when="midnight", backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
            )
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            handlers.append(file_handler)
        
        for handler in handlers:
            self.logger.addHandler(handler)

    def _setup_session(self):
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Cookie': COOKIE
        })

    def _load_state(self) -> Dict:
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                normalized = {}
                for k, v in state.items():
                    fid = int(k)
                    if isinstance(v, dict):
                        normalized[fid] = {'last_pid': int(v.get('last_pid', 0)), 'last_tid': int(v.get('last_tid', 0))}
                    else:
                        normalized[fid] = {'last_pid': int(v), 'last_tid': 0}
                return normalized
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_state(self):
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存状态失败: {e}")
    
    def _check_config(self):
        if not COOKIE or COOKIE == 'your_cookie_here':
            self.logger.warning("❌ Cookie 未配置")

        # 检查是否有任何一种发送方式
        has_sender = False
        if DINGTALK_WEBHOOK: has_sender = True
        if FEISHU_WEBHOOK: has_sender = True
        if FEISHU_APP_ID and FEISHU_TARGET_ID: has_sender = True

        if not has_sender:
            self.logger.warning("⚠️  未配置任何有效的通知方式 (钉钉Webhook / 飞书Webhook / 飞书API)")

        if FEISHU_WEBHOOK and not FEISHU_APP_ID:
            self.logger.warning("⚠️  飞书使用 Webhook 模式且未配置 AppID，图片将无法直接预览")

    def _get_livelastpost(self, fid: int, last_pid: int) -> Optional[Dict]:
        url = f"{BASE_URL}/forum.php"
        params = {'mod': 'misc', 'action': 'livelastpost', 'type': 'post', 'fid': fid, 'postid': last_pid}
        headers = {'Referer': f"{BASE_URL}/group-{fid}-1.html", 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}

        # 添加重试机制，最多重试2次
        for attempt in range(3):
            try:
                self.logger.debug(f"FID {fid}: 请求 livelastpost (尝试 {attempt + 1}/3)")
                response = self.session.get(url, params=params, headers=headers, timeout=15)

                # 检查HTTP状态码
                if response.status_code == 504:
                    self.logger.warning(f"FID {fid}: 服务器网关超时 (504)，论坛服务器可能负载过高或维护中")
                    if attempt < 2:  # 不是最后一次尝试
                        self.logger.info(f"FID {fid}: {5 * (attempt + 1)} 秒后重试...")
                        time.sleep(5 * (attempt + 1))
                        continue
                    return None

                if response.status_code != 200:
                    self.logger.warning(f"FID {fid}: HTTP {response.status_code} 错误")
                    return None

                # 检查响应内容是否包含登录提示
                response_text = response.text
                if 'not_loggedin' in response_text:
                    self.logger.warning(f"FID {fid}: Cookie 可能已失效")
                    return None
            
                if '504 Gateway Time-out' in response_text:
                    self.logger.warning(f"FID {fid}: 响应内容显示网关超时")
                    if attempt < 2:
                        self.logger.info(f"FID {fid}: {5 * (attempt + 1)} 秒后重试...")
                        time.sleep(5 * (attempt + 1))
                        continue
                    return None

                # 尝试解析JSON
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    self.logger.warning(f"FID {fid}: 响应不是有效JSON: {e}")
                    self.logger.debug(f"FID {fid}: 响应内容前200字符: {response_text[:200]}")
                    return None
            
                count = int(data.get('count', 0))
                if count > 0:
                    self.logger.info(f"FID {fid}: 发现 {count} 条新内容")
                    return data
                else:
                    self.logger.debug(f"FID {fid}: 暂无新内容 (count={count})")
                    return None
            
            except requests.exceptions.Timeout:
                self.logger.warning(f"FID {fid}: 请求超时 (尝试 {attempt + 1}/3)")
                if attempt < 2:
                    time.sleep(3)
                    continue
                return None

            except requests.exceptions.RequestException as e:
                self.logger.error(f"FID {fid}: 网络请求异常: {e}")
                if attempt < 2:
                    time.sleep(3)
                    continue
                return None

            except Exception as e:
                self.logger.error(f"FID {fid}: 处理 livelastpost 时出现异常: {e}")
                return None

        return None

    def _get_thread_detail(self, tid: int, target_pid: Optional[int]) -> Optional[Dict]:
        url = f"{BASE_URL}/api/mobile/index.php"
        params = {'version': '4', 'module': 'viewthread', 'tid': tid}
        try:
            response = self.session.get(url, params=params, timeout=15)
            data = response.json()
            if 'show_thread_nopermission' in str(data):
                return self._get_web_content_fallback(tid, fid_hint=None)
            if target_pid:
                found = False
                for post in data.get('Variables', {}).get('postlist', []):
                    if int(post.get('pid', 0)) == target_pid: found = True
                if not found: return self._get_web_content_fallback(tid, fid_hint=None)
            return data
        except Exception:
            return self._get_web_content_fallback(tid, fid_hint=None)

    def _extract_post_content(self, thread_data: Dict, target_pid: int) -> Optional[Dict]:
        try:
            if not isinstance(thread_data, dict): return None
            vars = thread_data.get('Variables', {})
            post_list = vars.get('postlist', [])
            target = next((p for p in post_list if int(p.get('pid', 0)) == target_pid), None)
            if not target: return None
            
            subject = vars.get('thread', {}).get('subject', '无标题')
            text, images = self._clean_content(target.get('message', ''))
            return {
                'subject': subject,
                'author': target.get('author', '未知'),
                'time': target.get('dateline', ''),
                'content': text,
                'images': images,
                'url': f"{BASE_URL}/thread-{vars.get('thread', {}).get('tid', '')}-1-1.html"
            }
        except Exception:
            return None

    def _extract_from_livelastpost(self, post_item: Dict, fid: int) -> Optional[Dict]:
        text, images = self._clean_content(post_item.get('message', ''))
        tid = self._extract_tid_from_message(post_item.get('message', ''))
        return {
            'subject': text[:30] + '...' if text else '新动态',
            'author': post_item.get('author', '未知'),
            'time': post_item.get('dateline', ''),
            'content': text,
            'images': images,
            'url': f"{BASE_URL}/thread-{tid}-1-1.html" if tid else f"{BASE_URL}/group-{fid}-1.html"
        }

    def _get_web_content_fallback(self, tid: int, fid_hint: Optional[int]) -> Tuple[Optional[str], Optional[List[str]]]:
        url = f"{BASE_URL}/thread-{tid}-1-1.html"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.encoding.lower() in ['gbk', 'gb2312']: resp.encoding = 'gbk'
            soup = BeautifulSoup(resp.text, 'html.parser')
            node = soup.find('td', class_='t_f')
            if not node: return "解析失败", []
            text = node.get_text(separator='\n').strip()
            images = []
            for img in node.find_all('img'):
                src = img.get('zoomfile') or img.get('file') or img.get('src')
                if src: images.append(urljoin(BASE_URL + '/', src))
            return text, images
        except Exception:
            return None, None

    def _clean_content(self, html_content: str) -> Tuple[str, List[str]]:
        if not html_content: return "", []
        soup = BeautifulSoup(html_content, 'html.parser')
        images = []
        for img in soup.find_all('img'):
            # 优先获取高清大图链接
            src = img.get('zoomfile') or img.get('file') or img.get('src')

            if src and 'smilies' not in src:
                # =========== 修复代码开始 ===========
                # 强力清洗 URL：去掉 ? 后面的所有参数
                # 比如 .jpg?imageMogr2... 会变成纯净的 .jpg
                if '?' in src:
                    src = src.split('?')[0]
                # =========== 修复代码结束 ===========

                full_url = urljoin(BASE_URL + '/', src)

                # 去重：防止同一张图被添加多次
                if full_url not in images:
                    images.append(full_url)

        for tag in soup(['script', 'style', 'img']):
            tag.decompose()
        return soup.get_text('\n').strip(), images

    def _extract_tid_from_message(self, html: str) -> Optional[int]:
        m = re.search(r'thread-(\d+)', html)
        return int(m.group(1)) if m else None

    def _format_message(self, post_data: Dict) -> str:
        t = post_data.get('time', '')
        if str(t).isdigit(): t = datetime.fromtimestamp(int(t)).strftime('%Y-%m-%d %H:%M:%S')
        content = post_data.get('content', '')
        if PREVIEW_LIMIT > 0: content = content[:PREVIEW_LIMIT]
        return f"### {post_data.get('subject')}\n**作者**: {post_data.get('author')}  **时间**: {t}\n\n{content}\n\n[🔗 查看原帖]({post_data.get('url')})"

    # ================= 钉钉专用：全能外链上传 =================
    def _universal_upload_for_dingtalk(self, img_url: str) -> str:
        """
        上传到自建图床：http://frp-cup.com:12245/upload/upload.html
        增加图片验证和错误处理
        """
        try:
            headers = {"Referer": BASE_URL + "/", "User-Agent": self.session.headers.get("User-Agent")}
            r = self.session.get(img_url, headers=headers, timeout=15)

            if r.status_code != 200:
                self.logger.warning(f"[图床] 下载图片失败: HTTP {r.status_code}")
                return img_url

            img_content = r.content

            # 验证内容是否为空
            if not img_content or len(img_content) < 100:
                self.logger.warning(f"[图床] 下载的图片太小或为空: {len(img_content)} bytes")
                return img_url

            # 严格验证：如果开头是 < !DOCTYPE 或 <html，说明下载的是网页报错
            if img_content.strip().startswith(b'<'):
                self.logger.warning(f"[图床] 下载到的是HTML页面(可能是防盗链或404): {img_url}")
                return img_url

            # 检查是否是有效的图片格式
            if not self._is_valid_image(img_content):
                self.logger.warning("[图床] 图片格式无效或损坏")
                return img_url

        except Exception as e:
            self.logger.warning(f"[图床] 下载图片异常: {e}")
            return img_url

        # 确定MIME类型和扩展名
        mime = 'image/jpeg'
        ext = '.jpg'
        if img_content.startswith(b'\x89PNG'): mime, ext = 'image/png', '.png'
        elif img_content.startswith(b'GIF8'): mime, ext = 'image/gif', '.gif'
        filename = f"img_{int(time.time())}_{random.randint(100,999)}{ext}"

        # 自建图床上传（优化版，适配国内网络环境）
        for attempt in range(3):  # 最多重试3次
            res = None  # 初始化res变量，避免作用域问题
            try:
                upload_url = "http://frp-cup.com:12245/upload/upload.html"

                # 构建multipart/form-data
                files = {'image': (filename, img_content, mime)}

                # 设置请求头（适配国内网络环境）
                headers = {
                    'Accept': 'application/json, text/javascript, */*; q=0.01',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',  # 调整语言优先级
                    'Connection': 'keep-alive',
                    'Origin': 'http://frp-cup.com:12245',
                    'Referer': 'http://frp-cup.com:12245/',
                    # 使用更通用的User-Agent，避免触发反爬虫
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': None  # 让requests自动设置multipart边界
                }

                self.logger.debug(f"[自建图床] 尝试上传 {filename} (尝试 {attempt + 1}/3)")

                # 发送上传请求（增加超时时间，禁用SSL验证）
                upload_timeout = 60 if attempt == 0 else 45  # 逐渐减少超时时间
                res = requests.post(
                    upload_url,
                    files=files,
                    headers=headers,
                    timeout=upload_timeout,
                    verify=False,
                    allow_redirects=True
                )

                # 检查响应
                if res.status_code == 200:
                    try:
                        data = res.json()
                        if data.get('code') == 200 and 'data' in data:
                            img_url_result = data['data'].get('url')
                            if img_url_result:
                                # URL中的\/需要转义
                                final_url = img_url_result.replace('\\/', '/')
                                self.logger.info(f"✅ [自建图床] 上传成功: {final_url}")
                                return final_url
                        else:
                            # 特殊处理"非法图片文件"错误
                            error_msg = data.get('error', '')
                            if '非法图片文件' in error_msg:
                                self.logger.warning(f"[自建图床] 服务器拒绝图片 (非法图片文件): {img_url}")
                                self.logger.debug(f"[自建图床] 图片大小: {len(img_content)} bytes")
                                # 对于非法图片文件，不再重试，直接返回原链接
                                return img_url
                            else:
                                self.logger.warning(f"[自建图床] API响应错误: {data}")
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"[自建图床] 响应不是有效JSON: {e}")
                        self.logger.debug(f"[自建图床] 响应内容: {res.text[:200]}")
                else:
                    self.logger.warning(f"[自建图床] HTTP {res.status_code} 错误")

            except requests.exceptions.ConnectionError as e:
                if "RemoteDisconnected" in str(e) or "Connection aborted" in str(e) or "Connection reset by peer" in str(e):
                    self.logger.warning(f"[自建图床] 连接被服务器断开 (尝试 {attempt + 1}/3): {e}")
                else:
                    self.logger.warning(f"[自建图床] 连接错误 (尝试 {attempt + 1}/3): {e}")
            except requests.exceptions.Timeout as e:
                self.logger.warning(f"[自建图床] 请求超时 ({upload_timeout if 'upload_timeout' in locals() else 60}s) (尝试 {attempt + 1}/3): {e}")
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"[自建图床] 网络请求异常 (尝试 {attempt + 1}/3): {e}")
            except Exception as e:
                self.logger.error(f"[自建图床] 未知异常 (尝试 {attempt + 1}/3): {e}")

            # 只有在非"非法图片文件"错误时才重试
            # 因为图片本身有问题，重试也没有意义
            should_retry = True
            if res and hasattr(res, 'status_code') and res.status_code == 200:
                try:
                    response_data = res.json()
                    if response_data.get('error') == '非法图片文件':
                        should_retry = False
                        self.logger.info("[自建图床] 图片文件非法，跳过重试")
                except:
                    pass

            if should_retry and attempt < 2:
                retry_delay = 2 * (attempt + 1)  # 2秒, 4秒
                self.logger.info(f"[自建图床] {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            elif not should_retry:
                break  # 跳出重试循环

        # 上传失败，返回原链接
        return img_url

    def _is_valid_image(self, image_data: bytes) -> bool:
        """
        验证图片数据是否有效
        """
        if not image_data or len(image_data) < 4:
            return False

        # 检查文件头标识
        # PNG: \x89PNG
        # JPEG: \xFF\xD8
        # GIF: GIF8
        # BMP: BM
        # WebP: RIFF....WEBP

        if image_data.startswith(b'\x89PNG'):
            return True
        elif image_data.startswith(b'\xFF\xD8'):
            return True
        elif image_data.startswith(b'GIF8'):
            return True
        elif image_data.startswith(b'BM'):
            return True
        elif len(image_data) > 12 and image_data.startswith(b'RIFF') and b'WEBP' in image_data[8:12]:
            return True

        # 检查是否包含HTML（下载失败的标志）
        if b'<html' in image_data.lower() or b'<!DOCTYPE' in image_data.lower():
            return False

        # 检查是否是其他常见的图片格式或二进制数据
        # 对于Discuz论坛的动态图片，可能不是标准格式但仍然有效
        # 只要不是HTML/XML内容就可以尝试上传

        return False

    # ================= 飞书专用：获取Token并上传 =================
    def _get_feishu_token(self) -> Optional[str]:
        now = time.time()
        if self.feishu_token and self.feishu_token_expire > now:
            return self.feishu_token
        if not (FEISHU_APP_ID and FEISHU_APP_SECRET):
            return None
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                self.feishu_token = data["tenant_access_token"]
                self.feishu_token_expire = now + int(data.get("expire", 3600)) - 60
                return self.feishu_token
        except Exception as e:
            self.logger.error(f"飞书 Token 获取失败: {e}")
            return None

    def _upload_to_feishu_server(self, img_url: str) -> Optional[str]:
        """
        将图片上传到飞书服务器，获取 image_key (用于直接显示)
        """
        token = self._get_feishu_token()
        if not token: return None

        try:
            # 下载图片
            headers = {"Referer": BASE_URL + "/", "User-Agent": self.session.headers.get("User-Agent")}
            r = self.session.get(img_url, headers=headers, timeout=15)
            if r.status_code != 200: return None
            
            # 上传飞书
            url = "https://open.feishu.cn/open-apis/im/v1/images"
            headers = {"Authorization": f"Bearer {token}"}
            # 飞书要求字段名为 image
            files = {"image_type": (None, "message"), "image": ("image.jpg", r.content)}
            resp = requests.post(url, headers=headers, files=files, timeout=20)
            data = resp.json()
            if data.get("code") == 0:
                key = data.get("data", {}).get("image_key")
                self.logger.info(f"✅ [飞书] 原生上传成功 key: {key}")
                return key
            else:
                self.logger.warning(f"[飞书] 上传失败: {data}")
        except Exception as e:
            self.logger.error(f"[飞书] 上传异常: {e}")
            return None

    # ================= 发送逻辑 =================

    def send_dingtalk(self, message: str, post_data: Dict = None) -> bool:
        webhook_url = DINGTALK_WEBHOOK
        if not webhook_url: return False

        final_markdown = message
        # 钉钉使用外链
        if post_data and post_data.get('images'):
            self.logger.info(f"钉钉：正在处理 {len(post_data['images'])} 张图片...")
            for img_url in post_data['images']:
                new_url = self._universal_upload_for_dingtalk(img_url)
                if new_url != img_url:
                    final_markdown += f"\n\n![图片]({new_url})"
                else:
                    final_markdown += f"\n\n[🖼️ 图片无法预览]({img_url})"
                time.sleep(0.5)

        # 加签
        if DINGTALK_SECRET:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
            hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            delimiter = '&' if '?' in webhook_url else '?'
            webhook_url = f"{webhook_url}{delimiter}timestamp={timestamp}&sign={sign}"

        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": post_data.get('subject', '新动态'), "text": final_markdown}
            }
            requests.post(webhook_url, json=payload, timeout=10)
            return True
        except Exception as e:
            self.logger.error(f"钉钉发送异常: {e}")
            return False

    def send_feishu(self, message: str, post_data: Dict = None) -> bool:
        # 1. 优先检查 Webhook
        webhook_url = FEISHU_WEBHOOK

        # 2. 如果没有 Webhook，检查是否具备 API 发送条件 (AppID + Secret + TargetID)
        use_api_mode = False
        if not webhook_url:
            if FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_TARGET_ID:
                use_api_mode = True
            else:
                self.logger.warning("飞书配置不完整：既无 Webhook，也无 TargetID/AppID，无法发送")
                return False

        # 构建卡片内容 (webhook 和 api 通用)
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": message
                }
            }
        ]

        # 图片处理逻辑
        if post_data and post_data.get('images'):
            self.logger.info(f"飞书：正在处理 {len(post_data['images'])} 张图片...")

            # 只要配置了 AppID/Secret，就可以尝试上传原图
            if FEISHU_APP_ID and FEISHU_APP_SECRET:
                for img_url in post_data['images']:
                    image_key = self._upload_to_feishu_server(img_url)
                    if image_key:
                        elements.append({
                            "tag": "img",
                            "img_key": image_key,
                            "alt": {"tag": "plain_text", "content": "图片"}
                        })
                    time.sleep(0.5)
            # 降级方案：使用外链
            else:
                for img_url in post_data['images']:
                    # 如果是 API 模式，无法渲染外链图片，只能给链接
                    new_url = self._universal_upload_for_dingtalk(img_url)
                    elements.append({
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"[🖼️ 点击查看图片]({new_url})"
                        }
                    })

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"DiscuzSentinel • {datetime.now().strftime('%H:%M:%S')}"}]
        })

        card_content = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": post_data.get('subject', '新动态')},
                "template": "blue"
            },
            "elements": elements
        }

        try:
            if use_api_mode:
                # =========== 模式 B: API 发送 (AppID + TargetID) ===========
                token = self._get_feishu_token()
                if not token:
                    self.logger.error("无法获取飞书 Token，发送失败")
                    return False

                # 判断 Target ID 类型
                receive_id_type = "chat_id" # 默认为群组/会话ID (oc_开头)
                if FEISHU_TARGET_ID.startswith("ou_"):
                    receive_id_type = "open_id"
                elif FEISHU_TARGET_ID.startswith("on_"):
                    receive_id_type = "union_id"
                elif "@" in FEISHU_TARGET_ID:
                    receive_id_type = "email"

                url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                payload = {
                    "receive_id": FEISHU_TARGET_ID,
                    "msg_type": "interactive",
                    "content": json.dumps(card_content) # API 模式下 content 必须是字符串
                }

                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                resp_data = resp.json()

                if resp_data.get("code") == 0:
                    self.logger.info("✅ [飞书] 消息发送成功 (API模式)")
                    return True
                else:
                    self.logger.error(f"[飞书] API 发送失败: {resp_data}")
                    return False

            else:
                # =========== 模式 A: Webhook 发送 ===========
                payload = {
                    "msg_type": "interactive",
                    "card": card_content
                }
                requests.post(webhook_url, json=payload, timeout=10)
                self.logger.info("✅ [飞书] 消息发送成功 (Webhook模式)")
                return True

        except Exception as e:
            self.logger.error(f"飞书发送异常: {e}")
            return False
    
    def run(self):
        self.logger.info(f"DiscuzSentinel 启动 | 监控: {TARGET_FIDS}")
        if not (FEISHU_APP_ID and FEISHU_APP_SECRET):
            self.logger.warning("提示: 飞书未配置 AppID/Secret，图片将以链接形式展示。配置后可直接显示大图。")

        while True:
            try:
                for fid in TARGET_FIDS:
                    fid_state = self.state.get(fid, {'last_pid': 0})
                    data = self._get_livelastpost(fid, fid_state.get('last_pid', 0))
                    if data:
                        # 收集所有新帖子，按时间顺序排序
                        new_posts = []
                        max_pid = fid_state.get('last_pid', 0)

                        # 首先按 PID 从小到大处理，确保不遗漏
                        for item in sorted(data.get('list', []), key=lambda x: int(x.get('pid', 0))):
                            pid = int(item.get('pid', 0))
                            if pid <= max_pid:
                                continue
                
                            # 获取帖子数据
                            post_data = self._extract_from_livelastpost(item, fid)
                            tid = self._extract_tid_from_message(item.get('message', ''))
                            if tid:
                                detail = self._get_thread_detail(tid, pid)
                                if detail:
                                    extracted = self._extract_post_content(detail, pid)
                                    if extracted:
                                        post_data = extracted

                            if post_data:
                                # 添加时间戳用于排序
                                post_data['_timestamp'] = self._parse_timestamp(post_data.get('time', ''))
                                post_data['_pid'] = pid
                                new_posts.append(post_data)

                            max_pid = max(max_pid, pid)

                        # 如果有新帖子，按时间顺序排序并立即推送
                        if new_posts:
                            # 按时间戳从小到大排序（旧时间在前）
                            new_posts.sort(key=lambda x: x['_timestamp'])

                            self.logger.info(f"FID {fid}: 发现 {len(new_posts)} 条新内容，开始按时间顺序推送")

                            for post_data in new_posts:
                                msg = self._format_message(post_data)
                                pid = post_data['_pid']

                                # 钉钉推送
                                if DINGTALK_WEBHOOK:
                                    self.send_dingtalk(msg, post_data)
                                # 飞书推送
                                if FEISHU_WEBHOOK:
                                    time.sleep(1)
                                    self.send_feishu(msg, post_data)

                                self.logger.info(f"已推送 PID {pid} (时间: {post_data.get('time', '未知')})")

                                # 推送间隔，避免触发限流
                                time.sleep(1.5)

                        # 更新状态
                        self.state.setdefault(fid, {})['last_pid'] = max_pid
                        self._save_state()

                    time.sleep(3)
                time.sleep(random.randint(30, 60))
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"主循环异常: {e}")
                time.sleep(60)

    def _parse_timestamp(self, time_str: str) -> float:
        """
        解析时间字符串为时间戳，用于排序
        """
        if not time_str:
            return 0.0

        # 如果已经是数字时间戳
        if str(time_str).isdigit():
            try:
                return float(time_str)
            except:
                pass

        # 如果是格式化的时间字符串，尝试解析
        try:
            # 常见的格式：2025-12-25 13:08:20
            if isinstance(time_str, str):
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                return dt.timestamp()
        except:
            pass

        # 如果解析失败，返回当前时间戳作为默认值
        return time.time()

if __name__ == "__main__":
    DiscuzSentinel().run()