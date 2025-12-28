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

CONFIG_FILE = os.getenv('CONFIG_FILE', 'config.json')

# 兼容旧的环境变量配置（向后兼容）
TARGET_FIDS_STR = os.getenv('DISCUZ_TARGET_FIDS', '147,148')
TARGET_FIDS = [int(fid.strip()) for fid in TARGET_FIDS_STR.split(',') if fid.strip()]

# Cookie
COOKIE = os.getenv('DISCUZ_COOKIE', 'your_cookie_here')

# 钉钉配置（全局默认）
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
DINGTALK_SECRET = os.getenv('DINGTALK_SECRET', '')

# 飞书配置（全局默认）
FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK', '')
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')

# 图床配置
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
        self._setup_logging()
        self.session = requests.Session()
        self.state = self._load_state()
        self._setup_session()

        # 加载配置文件
        self.config = self._load_config()

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
            handlers.append(file_handler)
        logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s', handlers=handlers)
        self.logger = logging.getLogger(__name__)

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
    
    def _load_config(self) -> Dict:
        """加载JSON配置文件，如果不存在则使用环境变量配置"""
        config = {
            "global": {
                "cookie": COOKIE,
                "dingtalk": {
                    "webhook": DINGTALK_WEBHOOK,
                    "secret": DINGTALK_SECRET
                },
                "feishu": {
                    "webhook": FEISHU_WEBHOOK,
                    "app_id": FEISHU_APP_ID,
                    "app_secret": FEISHU_APP_SECRET
                },
                "image_host": ZYCS_IMG_HOST,
                "preview_limit": PREVIEW_LIMIT
            },
            "fids": {}
        }

        # 如果配置文件存在，加载它
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self.logger.info(f"✅ 加载配置文件: {CONFIG_FILE}")

                    # 合并配置
                    if "global" in user_config:
                        config["global"].update(user_config["global"])

                    if "fids" in user_config:
                        config["fids"] = user_config["fids"]

                    # 如果配置文件中有fids，从中提取TARGET_FIDS
                    if config["fids"]:
                        global TARGET_FIDS
                        TARGET_FIDS = [int(fid) for fid in config["fids"].keys()]

            except Exception as e:
                self.logger.error(f"❌ 配置文件加载失败: {e}，使用默认配置")
        else:
            self.logger.info(f"ℹ️  未找到配置文件 {CONFIG_FILE}，使用环境变量配置")

        return config

    def _check_config(self):
        # 检查全局配置
        global_config = self.config.get("global", {})
        has_global_dingtalk = bool(global_config.get("dingtalk", {}).get("webhook"))
        has_global_feishu = bool(global_config.get("feishu", {}).get("webhook"))

        if not global_config.get("cookie") or global_config.get("cookie") == 'your_cookie_here':
            self.logger.warning("❌ Cookie 未配置")

        # 检查每个FID的配置
        fid_configs = self.config.get("fids", {})
        if not fid_configs and not has_global_dingtalk and not has_global_feishu:
            self.logger.warning("⚠️  未配置任何通知 Webhook")

        for fid, fid_config in fid_configs.items():
            fid_name = fid_config.get("name", f"FID{fid}")
            has_dingtalk = bool(fid_config.get("dingtalk", {}).get("webhook")) or has_global_dingtalk
            has_feishu = bool(fid_config.get("feishu", {}).get("webhook")) or has_global_feishu

            if not has_dingtalk and not has_feishu:
                self.logger.warning(f"⚠️  {fid_name} (FID:{fid}) 未配置推送渠道")

            # 检查飞书图片配置
            feishu_config = fid_config.get("feishu", {})
            if (feishu_config.get("webhook") or has_global_feishu) and not (feishu_config.get("app_id") or global_config.get("feishu", {}).get("app_id")):
                self.logger.warning(f"⚠️  {fid_name} (FID:{fid}) 飞书未配置 AppID/Secret，图片将无法直接显示，仅显示链接")

    def _get_livelastpost(self, fid: int, last_pid: int) -> Optional[Dict]:
        url = f"{BASE_URL}/forum.php"
        params = {'mod': 'misc', 'action': 'livelastpost', 'type': 'post', 'fid': fid, 'postid': last_pid}
        headers = {'Referer': f"{BASE_URL}/group-{fid}-1.html", 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            if 'not_loggedin' in response.text:
                self.logger.warning("Cookie 可能已失效")
                return None
            data = response.json()
            if int(data.get('count', 0)) > 0:
                self.logger.info(f"FID {fid}: 发现 {data.get('count')} 条新内容")
                return data
            return None
        except Exception:
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
            src = img.get('zoomfile') or img.get('file') or img.get('src')
            if src and 'smilies' not in src:
                images.append(urljoin(BASE_URL + '/', src))
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
        全能上传：Catbox.moe (强力) -> CF Imgur模式 -> CF Telegraph模式
        """
        try:
            headers = {"Referer": BASE_URL + "/", "User-Agent": self.session.headers.get("User-Agent")}
            r = self.session.get(img_url, headers=headers, timeout=15)
            if r.status_code != 200: return img_url
            if len(r.content) < 100 or r.content.strip().startswith(b'<'): return img_url
            img_content = r.content
        except: return img_url

        mime = 'image/jpeg'
        ext = '.jpg'
        if img_content.startswith(b'\x89PNG'): mime, ext = 'image/png', '.png'
        elif img_content.startswith(b'GIF8'): mime, ext = 'image/gif', '.gif'
        filename = f"img_{int(time.time())}_{random.randint(100,999)}{ext}"

        # 1. Catbox
        try:
            files = {'fileToUpload': (filename, img_content, mime)}
            res = requests.post("https://catbox.moe/user/api.php", data={'reqtype': 'fileupload'}, files=files, timeout=30)
            if res.status_code == 200 and res.text.startswith("http"):
                self.logger.info(f"✅ [钉钉] Catbox 上传: {res.text.strip()}")
                return res.text.strip()
        except: pass

        # 2. CF Pages
        if ZYCS_IMG_HOST:
            try:
                # Imgur Mode
                upload_url = ZYCS_IMG_HOST.rstrip('/') + "/upload"
                files = {'image': (filename, img_content, mime)}
                res = requests.post(upload_url, headers={'Authorization': 'Client-ID 546c25a59c58ad7'}, files=files, data={'type': 'file'}, timeout=15)
                if res.status_code == 200:
                    link = res.json().get('data', {}).get('link')
                    if link: return link
            except: pass
            
        return img_url

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

    def send_dingtalk(self, message: str, post_data: Dict = None, dingtalk_config: Dict = None) -> bool:
        if not dingtalk_config:
            dingtalk_config = self.config.get("global", {}).get("dingtalk", {})

        webhook_url = dingtalk_config.get("webhook", "")
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
        secret = dingtalk_config.get("secret", "")
        if secret:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
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

    def send_feishu(self, message: str, post_data: Dict = None, feishu_config: Dict = None) -> bool:
        if not feishu_config:
            feishu_config = self.config.get("global", {}).get("feishu", {})

        webhook_url = feishu_config.get("webhook", "")
        if not webhook_url: return False

        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": message
                }
            }
        ]

        # 飞书图片处理
        if post_data and post_data.get('images'):
            self.logger.info(f"飞书：正在处理 {len(post_data['images'])} 张图片...")

            app_id = feishu_config.get("app_id", "")
            app_secret = feishu_config.get("app_secret", "")

            if app_id and app_secret:
                # 方式A：配置了 AppID -> 上传到飞书 -> 使用 image 标签显示大图
                # 临时设置飞书的token获取参数
                global FEISHU_APP_ID, FEISHU_APP_SECRET
                old_app_id, old_app_secret = FEISHU_APP_ID, FEISHU_APP_SECRET
                FEISHU_APP_ID, FEISHU_APP_SECRET = app_id, app_secret

                try:
                    for img_url in post_data['images']:
                        image_key = self._upload_to_feishu_server(img_url)
                        if image_key:
                            elements.append({
                                "tag": "img",
                                "img_key": image_key,
                                "alt": {"tag": "plain_text", "content": "图片"}
                            })
                        time.sleep(0.5)
                finally:
                    # 恢复全局配置
                    FEISHU_APP_ID, FEISHU_APP_SECRET = old_app_id, old_app_secret
            else:
                # 方式B：没配置 AppID -> 使用 Catbox 外链 -> 显示为点击链接
                # (因为飞书 Webhook 无法直接渲染外链图片)
                for img_url in post_data['images']:
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

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": post_data.get('subject', '新动态')},
                    "template": "blue"
                },
                "elements": elements
            }
        }

        try:
            requests.post(webhook_url, json=payload, timeout=10)
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

                                # 根据FID获取推送配置
                                fid_config = self.config.get("fids", {}).get(str(fid), {})
                                global_config = self.config.get("global", {})

                                # 钉钉推送
                                dingtalk_config = fid_config.get("dingtalk") or global_config.get("dingtalk", {})
                                if dingtalk_config.get("webhook"):
                                    self.send_dingtalk(msg, post_data, dingtalk_config)

                                # 飞书推送
                                feishu_config = fid_config.get("feishu") or global_config.get("feishu", {})
                                if feishu_config.get("webhook"):
                                    time.sleep(1)
                                    self.send_feishu(msg, post_data, feishu_config)

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