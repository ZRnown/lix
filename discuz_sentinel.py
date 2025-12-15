#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DiscuzSentinel - Discuz! 论坛多驿站监控系统
采用双接口模式：livelastpost (侦察) + Mobile API (抓取)
"""

import json
import logging
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
from bs4 import BeautifulSoup

import requests
from bs4 import BeautifulSoup

# 尝试加载 python-dotenv（如果安装了）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==================== 配置区域 ====================

# 目标驿站 FID 列表（需要监控的板块ID）
# 支持环境变量 DISCUZ_TARGET_FIDS，格式：147,148
TARGET_FIDS_STR = os.getenv('DISCUZ_TARGET_FIDS', '147,148')
TARGET_FIDS = [int(fid.strip()) for fid in TARGET_FIDS_STR.split(',') if fid.strip()]

# 列表页抓取页数（forumdisplay），默认抓取1页
LIST_PAGES = int(os.getenv('LIST_PAGES', '1'))

# Cookie（优先从环境变量读取，否则使用硬编码）
# 建议使用环境变量：export DISCUZ_COOKIE="your_cookie_here"
COOKIE = os.getenv('DISCUZ_COOKIE', 'your_cookie_here')

# Webhook URLs（优先从环境变量读取）
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', 'https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN')
DINGTALK_SECRET = os.getenv('DINGTALK_SECRET', '')  # 钉钉加签密钥（可选）
DINGTALK_KEYWORD = os.getenv('DINGTALK_KEYWORD', '')  # 钉钉自定义关键词（可选，消息需包含）
FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK', 'https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN')

# 系统告警 Webhook（用于 Cookie 失效等关键错误）
SYSTEM_ALERT_WEBHOOK = os.getenv('SYSTEM_ALERT_WEBHOOK', '')  # 可选，如果设置则发送系统告警

# 图片处理模式：'direct'（直接链接）、'text_only'（仅文字）、'upload_feishu'（上传到飞书）
IMAGE_MODE = os.getenv('IMAGE_MODE', 'direct')  # 默认直接链接

# 文本预览长度（0 或负数表示不截断）
PREVIEW_LIMIT = int(os.getenv('PREVIEW_LIMIT', '4000'))

# 论坛基础URL
BASE_URL = "https://www.55188.com"

# 状态文件路径
STATE_FILE = "monitor_state.json"

# 日志配置
LOG_FILE = os.getenv('LOG_FILE', 'discuz_sentinel.log')
LOG_LEVEL = logging.INFO if os.getenv('LOG_LEVEL', 'INFO').upper() == 'INFO' else logging.DEBUG

# Cookie 失效检测标志（用于告警）
_cookie_invalid_flag = False

# ==================== 核心类 ====================


class DiscuzSentinel:
    """Discuz! 论坛监控核心类"""

    def __init__(self):
        """初始化监控器"""
        # 必须先初始化日志系统，因为其他方法可能会使用 logger
        self._setup_logging()
        self.session = requests.Session()
        self.state = self._load_state()
        self._setup_session()
        self._check_config()

    def _setup_logging(self):
        """配置日志系统"""
        logging.basicConfig(
            level=LOG_LEVEL,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.last_alert_time = 0  # 上次告警时间戳（用于冷却机制）

    def _setup_session(self):
        """配置 Session 和 Headers"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cookie': COOKIE
        })

    def _load_state(self) -> Dict[int, Dict[str, int]]:
        """从文件加载监控状态（每个 FID 的 last_pid / last_tid）"""
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                self.logger.info(f"已加载状态文件: {state}")
                # 兼容老格式：如果值是 int，则转换为 dict
                normalized = {}
                for k, v in state.items():
                    fid = int(k)
                    if isinstance(v, dict):
                        normalized[fid] = {
                            'last_pid': int(v.get('last_pid', 0)),
                            'last_tid': int(v.get('last_tid', 0))
                        }
                    else:
                        normalized[fid] = {'last_pid': int(v), 'last_tid': 0}
                return normalized
        except FileNotFoundError:
            self.logger.info("状态文件不存在，创建新状态")
            return {}
        except Exception as e:
            self.logger.error(f"加载状态文件失败: {e}")
            return {}

    def _save_state(self):
        """保存监控状态到文件"""
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"状态已保存: {self.state}")
        except Exception as e:
            self.logger.error(f"保存状态文件失败: {e}")
    
    def _check_config(self):
        """检查配置是否正确"""
        issues = []
        
        # 检查 Cookie
        if not COOKIE or COOKIE == 'your_cookie_here':
            issues.append("❌ Cookie 未配置或使用默认值，请设置 DISCUZ_COOKIE 环境变量或编辑 .env 文件")
        
        # 检查 Webhook 配置
        webhook_configured = False
        if DINGTALK_WEBHOOK and DINGTALK_WEBHOOK != 'https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN':
            if 'dingtalk' in DINGTALK_WEBHOOK:
                webhook_configured = True
                self.logger.info("✅ 钉钉 Webhook 已配置")
        
        if FEISHU_WEBHOOK and FEISHU_WEBHOOK != 'https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN':
            if 'feishu' in FEISHU_WEBHOOK:
                webhook_configured = True
                self.logger.info("✅ 飞书 Webhook 已配置")
        
        if not webhook_configured:
            issues.append("⚠️  未配置 Webhook（DINGTALK_WEBHOOK 或 FEISHU_WEBHOOK），Cookie 失效时将无法收到告警通知")
        
        # 检查 FID 配置
        if not TARGET_FIDS:
            issues.append("❌ 未配置监控驿站（DISCUZ_TARGET_FIDS）")
        
        # 输出检查结果
        if issues:
            self.logger.warning("=" * 60)
            self.logger.warning("配置检查发现问题：")
            for issue in issues:
                self.logger.warning(f"  {issue}")
            self.logger.warning("=" * 60)
            self.logger.warning("提示：")
            self.logger.warning("  1. 复制 env.example 为 .env：cp env.example .env")
            self.logger.warning("  2. 编辑 .env 文件，填入实际配置")
            self.logger.warning("  3. 确保 Cookie 有效（从浏览器 F12 获取）")
            self.logger.warning("=" * 60)
        else:
            self.logger.info("✅ 配置检查通过")

    def _get_livelastpost(self, fid: int, last_pid: int) -> Optional[Dict]:
        """
        调用 livelastpost 接口检测新内容（侦察兵）
        
        Args:
            fid: 驿站ID
            last_pid: 上次处理的 PID
            
        Returns:
            包含新内容的字典，如果没有新内容返回 None
        """
        url = f"{BASE_URL}/forum.php"
        params = {
            'mod': 'misc',
            'action': 'livelastpost',
            'type': 'post',
            'fid': fid,
            'postid': last_pid
        }
        
        # 设置 Referer 模拟从驿站页面点击
        headers = {
            'Referer': f"{BASE_URL}/group-{fid}-1.html"
        }
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            # 处理编码（Discuz 可能返回 gbk 编码）
            if response.encoding.lower() in ['gbk', 'gb2312']:
                response.encoding = 'gbk'
            else:
                response.encoding = response.apparent_encoding or 'utf-8'
            
            # 检查响应内容，检测 Cookie 失效
            response_text = response.text
            if 'not_loggedin' in response_text or '请先登录' in response_text:
                self.logger.warning(f"FID {fid}: livelastpost 返回未登录错误，Cookie 可能已失效")
                self._send_cookie_invalid_alert("livelastpost API 返回未登录错误")
                return None
            
            # 尝试解析 JSON
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                # 如果不是 JSON，可能是 Cookie 无效或返回了 HTML 页面
                self.logger.warning(f"FID {fid}: livelastpost 返回非 JSON 格式: {e}")
                self.logger.warning(f"响应状态码: {response.status_code}")
                self.logger.warning(f"响应内容前500字符: {response_text[:500]}")
                
                # 检查是否是登录页面或权限错误
                if '登录' in response_text or 'login' in response_text.lower():
                    self.logger.error(f"FID {fid}: 返回登录页面，Cookie 可能已失效")
                    self._send_cookie_invalid_alert("livelastpost API 返回登录页面，Cookie 可能已失效")
                elif response.status_code != 200:
                    self.logger.error(f"FID {fid}: HTTP 状态码错误: {response.status_code}")
                
                return None
            
            # 检查是否有新内容（count 可能是字符串）
            count = data.get('count', 0)
            try:
                count = int(count) if isinstance(count, str) else count
            except (ValueError, TypeError):
                count = 0
            
            if count == 0:
                return None
            
            self.logger.info(f"FID {fid}: 发现 {count} 条新内容")
            return data
            
        except requests.exceptions.Timeout:
            self.logger.error(f"FID {fid}: 请求超时")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"FID {fid}: 请求失败: {e}")
            return None
        except Exception as e:
            self.logger.error(f"FID {fid}: 处理 livelastpost 时出错: {e}")
            return None

    def _get_thread_list(self, fid: int, pages: int = 1) -> List[Dict]:
        """
        通过 forumdisplay 列表页解析帖子列表，精确识别锁帖与普通帖

        Args:
            fid: 驿站ID
            pages: 抓取的页数（从1开始）
        Returns:
            列表，每项包含 tid/title/author/dateline/is_locked
        """
        threads: List[Dict] = []
        seen: set = set()
        headers = {'Referer': f"{BASE_URL}/forum.php"}

        for page in range(1, pages + 1):
            url = f"{BASE_URL}/forum.php?mod=forumdisplay&fid={fid}&page={page}"
            try:
                resp = self.session.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                if resp.encoding and resp.encoding.lower() in ['gbk', 'gb2312']:
                    resp.encoding = 'gbk'
                else:
                    resp.encoding = resp.apparent_encoding or 'utf-8'
                html = resp.text

                soup = BeautifulSoup(html, 'html.parser')
                # Discuz 列表结构：id="normalthread_XXXX"
                items = soup.find_all(id=re.compile(r'^normalthread_(\d+)'))
                for item in items:
                    try:
                        tid_str = item.get('id', '').split('_')[1]
                        tid = int(tid_str)
                        if tid in seen:
                            continue
                        seen.add(tid)

                        # 锁帖识别：folder_lock.gif
                        is_locked = False
                        icon_td = item.find('td', class_='icn')
                        if icon_td:
                            img = icon_td.find('img')
                            if img and 'folder_lock' in (img.get('src') or ''):
                                is_locked = True

                        title_node = item.find('a', class_='xst')
                        title = title_node.get_text(strip=True) if title_node else f"TID {tid}"

                        author = "未知"
                        dateline = ""
                        by_nodes = item.find_all('td', class_='by')
                        if by_nodes:
                            author_node = by_nodes[0].find('cite')
                            if author_node:
                                author = author_node.get_text(strip=True)
                            time_node = by_nodes[0].find('em')
                            if time_node:
                                dateline = time_node.get_text(strip=True)

                        threads.append({
                            'tid': tid,
                            'title': title,
                            'author': author,
                            'dateline': dateline,
                            'is_locked': is_locked,
                        })
                    except Exception:
                        continue

                self.logger.info(f"FID {fid}: 列表页第 {page} 页解析 {len(items)} 条，累计 {len(threads)} 条")
            except Exception as e:
                self.logger.error(f"FID {fid}: 获取列表页第 {page} 页失败: {e}")
                continue

        return threads

    def _get_thread_detail(self, tid: int, target_pid: Optional[int]) -> Optional[Dict]:
        """
        调用 Mobile API 获取帖子完整内容（特种兵）
        
        Args:
            tid: 主题ID
            target_pid: 目标楼层PID
            
        Returns:
            包含帖子详细信息的字典
        """
        url = f"{BASE_URL}/api/mobile/index.php"
        params = {
            'version': '4',
            'module': 'viewthread',
            'tid': tid
        }
        
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            # 处理编码
            if response.encoding.lower() in ['gbk', 'gb2312']:
                response.encoding = 'gbk'
            else:
                response.encoding = response.apparent_encoding or 'utf-8'
            
            data = response.json()
            
            # 检查权限
            variables = data.get('Variables', {})
            if variables.get('auth') is None:
                self.logger.warning(f"TID {tid}: Mobile API 返回 auth 为空，可能 Cookie 已失效")
                self._send_cookie_invalid_alert("Mobile API 返回 auth 为空")
            
            # 检查是否有权限错误
            if 'show_thread_nopermission' in str(data) or 'not_loggedin' in str(data):
                self.logger.warning(f"TID {tid}: 无权限访问，可能 Cookie 已失效")
                self._send_cookie_invalid_alert("Mobile API 返回无权限错误")
                return self._get_web_content_fallback(tid, fid_hint=None)
            
            # 如果指定了目标 PID，则检查是否存在（处理分页问题）
            if target_pid is not None:
                post_list = variables.get('postlist', [])
                found_pid = False
                for post in post_list:
                    if int(post.get('pid', 0)) == target_pid:
                        found_pid = True
                        break
                
                # 如果找不到目标 PID，可能是分页问题，返回 None 让调用者回退
                if not found_pid and post_list:
                    self.logger.debug(f"TID {tid}: Mobile API 返回的数据中未找到 PID {target_pid}，可能在后续页面，回退使用列表/网页内容")
                    return self._get_web_content_fallback(tid, fid_hint=None)
            
            return data
            
        except requests.exceptions.Timeout:
            self.logger.error(f"TID {tid}: Mobile API 请求超时")
            return self._get_web_content_fallback(tid, fid_hint=None)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"TID {tid}: Mobile API 请求失败: {e}")
            return self._get_web_content_fallback(tid, fid_hint=None)
        except json.JSONDecodeError as e:
            self.logger.error(f"TID {tid}: Mobile API 返回非 JSON 格式: {e}")
            return self._get_web_content_fallback(tid, fid_hint=None)
        except Exception as e:
            self.logger.error(f"TID {tid}: 处理 Mobile API 时出错: {e}")
            return self._get_web_content_fallback(tid, fid_hint=None)

    def _extract_post_content(self, thread_data: Dict, target_pid: int) -> Optional[Dict]:
        """
        从 Mobile API 返回的数据中提取指定 PID 的楼层内容
        
        Args:
            thread_data: Mobile API 返回的完整数据
            target_pid: 目标楼层 PID
            
        Returns:
            包含清洗后内容的字典
        """
        try:
            variables = thread_data.get('Variables', {})
            thread_info = variables.get('thread', {})
            post_list = variables.get('postlist', [])
            
            # 查找目标 PID 的楼层
            target_post = None
            for post in post_list:
                if int(post.get('pid', 0)) == target_pid:
                    target_post = post
                    break
            
            if not target_post:
                self.logger.warning(f"PID {target_pid}: 在帖子中未找到对应楼层，尝试回退到网页解析")
                return None
            
            # 提取标题（使用主题标题）
            subject = thread_info.get('subject', '无标题')
            
            # 提取作者信息
            author = target_post.get('author', '未知')
            author_id = target_post.get('authorid', '')
            
            # 提取时间
            post_time = target_post.get('dateline', '')
            if post_time:
                try:
                    post_time = datetime.fromtimestamp(int(post_time)).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    post_time = str(post_time)
            
            # 提取并清洗正文
            message = target_post.get('message', '')

            # 检查屏蔽提示，若存在则走网页回退
            if "内容自动屏蔽" in message or "作者被禁止" in message:
                tid = thread_info.get('tid', '')
                self.logger.info(f"TID {tid} PID {target_pid}: API 返回屏蔽提示，尝试网页回退")
                return None

            text_content, images = self._clean_content(message)
            
            # 构建跳转链接
            tid = thread_info.get('tid', '')
            thread_url = f"{BASE_URL}/thread-{tid}-1-1.html" if tid else ""
            
            return {
                'subject': subject,
                'author': author,
                'author_id': author_id,
                'time': post_time,
                'content': text_content,
                'images': images,
                'url': thread_url,
                'pid': target_pid,
                'tid': tid
            }
            
        except Exception as e:
            self.logger.error(f"提取内容时出错: {e}")
            return None

    def _extract_tid_from_message(self, message_html: str) -> Optional[int]:
        """
        从 message HTML 中提取 TID（帖子ID）
        
        注意：livelastpost 返回的 message 中可能不包含链接，这是正常情况
        如果提取不到 TID，应该直接使用 livelastpost 的内容，不要报错
        
        Args:
            message_html: HTML 格式的消息内容
            
        Returns:
            TID 或 None（提取不到是正常情况，不报错）
        """
        if not message_html:
            return None
        
        # 尝试从链接中提取 tid
        # 例如: https://www.55188.com/thread-37571572-1-1.html
        # 或者: thread-37571572-1-1.html
        patterns = [
            r'thread-(\d+)',  # 标准格式
            r'/thread-(\d+)-',  # 带路径的格式
            r'href=["\']?[^"\']*thread-(\d+)',  # 在链接中的格式
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message_html)
            if match:
                try:
                    tid = int(match.group(1))
                    self.logger.debug(f"从 message 中提取到 TID: {tid}")
                    return tid
                except (ValueError, IndexError):
                    continue
        
        # 提取不到是正常情况，不记录警告
        return None
    
    def _send_cookie_invalid_alert(self, reason: str):
        """
        发送 Cookie 失效告警
        
        使用时间戳冷却机制，避免告警死锁：
        - 如果24小时内已告警过，则跳过（防止重复告警）
        - 如果超过24小时，可以再次告警（避免永久失效）
        
        Args:
            reason: 失效原因
        """
        global _cookie_invalid_flag
        
        current_time = time.time()
        cooldown_period = 24 * 3600  # 24小时冷却期
        
        # 如果24小时内已经报过警，则跳过（防止重复告警）
        if current_time - self.last_alert_time < cooldown_period:
            self.logger.debug(f"Cookie 失效告警冷却中，距离上次告警 {int((current_time - self.last_alert_time) / 3600)} 小时")
            return
        
        # 更新告警时间戳
        self.last_alert_time = current_time
        _cookie_invalid_flag = True
        
        alert_message = f"""🚨 **DiscuzSentinel 系统告警**

**告警类型**: Cookie 失效

**原因**: {reason}

**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**处理建议**:
1. 重新登录论坛获取新的 Cookie
2. 更新环境变量 DISCUZ_COOKIE 或 .env 文件
3. **重要：必须重启监控程序**（程序不会自动读取新的 .env 文件）

**影响**: 监控程序可能无法获取完整内容，建议尽快处理。

**注意**: 如果已更新 Cookie 但未重启程序，告警将在24小时后再次发送。
"""
        
        # 发送告警到所有配置的 Webhook（系统告警 > 钉钉 > 飞书）
        # 如果都配置了，会同时发送到多个渠道，确保能收到通知
        webhooks_to_send = []
        
        # 1. 优先使用系统告警 Webhook
        if SYSTEM_ALERT_WEBHOOK and SYSTEM_ALERT_WEBHOOK not in ['https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN', 
                                                                   'https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN']:
            webhooks_to_send.append(('system', SYSTEM_ALERT_WEBHOOK))
        
        # 2. 如果配置了钉钉 Webhook，也发送到钉钉
        if DINGTALK_WEBHOOK and DINGTALK_WEBHOOK != 'https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN':
            if 'dingtalk' in DINGTALK_WEBHOOK:
                webhooks_to_send.append(('dingtalk', DINGTALK_WEBHOOK))
        
        # 3. 如果配置了飞书 Webhook，也发送到飞书
        if FEISHU_WEBHOOK and FEISHU_WEBHOOK != 'https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN':
            if 'feishu' in FEISHU_WEBHOOK:
                webhooks_to_send.append(('feishu', FEISHU_WEBHOOK))
        
        # 发送到所有配置的 Webhook
        success_count = 0
        for webhook_type, webhook_url in webhooks_to_send:
            try:
                if webhook_type in ['system', 'dingtalk']:
                    # 发送到钉钉
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {
                            "title": "🚨 Cookie 失效告警",
                            "text": alert_message
                        }
                    }
                    response = requests.post(webhook_url, json=payload, timeout=10)
                    response.raise_for_status()
                    result = response.json()
                    if result.get('errcode') == 0:
                        success_count += 1
                        self.logger.info(f"Cookie 失效告警已发送到 {webhook_type}")
                
                elif webhook_type == 'feishu':
                    # 发送到飞书
                    payload = {
                        "msg_type": "interactive",
                        "card": {
                            "config": {"wide_screen_mode": True},
                            "header": {
                                "title": {"tag": "plain_text", "content": "🚨 Cookie 失效告警"},
                                "template": "red"
                            },
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "content": alert_message,
                                    "tag": "lark_md"
                                }
                            }]
                        }
                    }
                    response = requests.post(webhook_url, json=payload, timeout=10)
                    response.raise_for_status()
                    result = response.json()
                    if result.get('code') == 0:
                        success_count += 1
                        self.logger.info(f"Cookie 失效告警已发送到 {webhook_type}")
                
                # 避免请求过快
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"发送告警到 {webhook_type} 失败: {e}")
        
        if success_count > 0:
            self.logger.warning(f"Cookie 失效告警已发送到 {success_count} 个渠道")
        else:
            self.logger.warning("未配置有效的告警 Webhook，无法发送 Cookie 失效告警通知")

    def _get_tid_by_pid(self, pid: int) -> Optional[int]:
        """
        通过 PID 获取 TID
        注意：Discuz Mobile API 通常不支持直接通过 pid 获取 tid
        这个方法主要用于尝试其他可能的 API，如果失败会返回 None
        实际使用中，优先使用 _extract_tid_from_message 方法
        
        Args:
            pid: 帖子/楼层 ID
            
        Returns:
            TID 或 None
        """
        # 注意：Discuz Mobile API 的 viewthread 需要 tid，不支持直接通过 pid 查询
        # 这个方法可能不会成功，但保留作为备用方案
        # 实际使用中，应该优先从 message HTML 中提取 tid
        self.logger.debug(f"尝试通过 PID {pid} 获取 TID（可能不支持）")
        return None

    def _extract_from_livelastpost(self, post_item: Dict, fid: int) -> Optional[Dict]:
        """
        直接从 livelastpost 返回的数据中提取内容
        （当无法获取 TID 或 Mobile API 失败时的回退方案）
        
        Args:
            post_item: livelastpost 返回的单个帖子数据
            fid: 驿站ID
            
        Returns:
            包含清洗后内容的字典
        """
        try:
            author = post_item.get('author', '未知')
            author_id = post_item.get('authorid', '')
            dateline = post_item.get('dateline', '')
            message_html = post_item.get('message', '')
            
            # 清洗内容
            text_content, images = self._clean_content(message_html)
            
            # 尝试从 message 中提取 tid 和构建链接
            tid = self._extract_tid_from_message(message_html)
            if tid:
                thread_url = f"{BASE_URL}/thread-{tid}-1-1.html"
            else:
                # 如果提取不到 tid，使用驿站链接
                thread_url = f"{BASE_URL}/group-{fid}-1.html"
            
            # 尝试提取标题（从 message 中）
            subject = "新动态"
            if text_content:
                # 取前50个字符作为标题
                subject = text_content[:50].replace('\n', ' ').strip()
                if len(text_content) > 50:
                    subject += "..."
            
            return {
                'subject': subject,
                'author': author,
                'author_id': author_id,
                'time': dateline,
                'content': text_content,
                'images': images,
                'url': thread_url,
                'pid': post_item.get('pid'),
                'tid': tid
            }
            
        except Exception as e:
            self.logger.error(f"从 livelastpost 数据提取内容时出错: {e}")
            return None

    def _get_web_content_fallback(self, tid: int, fid_hint: Optional[int]) -> Tuple[Optional[str], Optional[List[str]]]:
        """
        当 API 返回屏蔽或无法获取内容时，回退到网页抓取

        Args:
            tid: 帖子ID
            fid_hint: 可选，fid 用于构造 Referer（若无则使用通用 Referer）
        """
        url = f"{BASE_URL}/thread-{tid}-1-1.html"
        headers = self.session.headers.copy()
        headers['Referer'] = f"{BASE_URL}/forum.php?mod=forumdisplay&fid={fid_hint or ''}"

        try:
            resp = self.session.get(url, headers=headers, timeout=15)
            if resp.encoding and resp.encoding.lower() in ['gbk', 'gb2312']:
                resp.encoding = 'gbk'
            else:
                resp.encoding = resp.apparent_encoding or 'utf-8'

            soup = BeautifulSoup(resp.text, 'html.parser')
            content_node = soup.find('td', class_='t_f')
            if not content_node:
                return "⚠️ 网页解析失败，未找到内容节点。", []

            # 提取文本
            text = content_node.get_text(separator='\n').strip()

            # 提取图片
            images = []
            seen_urls = set()
            for img in content_node.find_all('img'):
                img_url = img.get('zoomfile') or img.get('file') or img.get('src') or img.get('data-src')
                if img_url:
                    if not img_url.startswith(('http:', 'https:')):
                        img_url = urljoin(BASE_URL + '/', img_url)
                    elif img_url.startswith('//'):
                        img_url = 'https:' + img_url
                    if img_url not in seen_urls:
                        seen_urls.add(img_url)
                        images.append(img_url)

            # 如果网页也提示屏蔽，则返回权限不足提示
            if "内容自动屏蔽" in text or "作者被禁止" in text:
                return "🔒 [权限不足] 您的账号无法查看此贴（可能需要付费或订阅）。", images

            return text, images

        except Exception as e:
            self.logger.error(f"网页回退抓取失败: {e}")
            return None, None

    def _clean_content(self, html_content: str) -> Tuple[str, List[str]]:
        """
        高级清洗：将 Discuz HTML 转成排版良好的 Markdown
        - 保留段落/换行 (p/div/br)
        - 保留加粗（strong/b/font 有 color）
        - 图文混排：图片在原位置插入 ![图片](url)
        - 去除 script/style/广告
        """
        from bs4 import NavigableString, Tag

        if not html_content:
            return "", []

        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. 移除干扰元素
        for tag in soup(['script', 'style', 'iframe', 'embed', 'object']):
            tag.decompose()

        images: List[str] = []
        seen_urls: set = set()

        def normalize_img_url(src: str) -> Optional[str]:
            if not src:
                return None
            if 'common/none.gif' in src or 'smilies' in src:
                return None
            if not src.startswith(('http:', 'https:')):
                src = urljoin(BASE_URL + '/', src)
            elif src.startswith('//'):
                src = 'https:' + src
            return src

        def traverse(node) -> str:
            if isinstance(node, NavigableString):
                text = str(node)
                # 保留必要空格，压缩连续空白
                text = re.sub(r'\s+', ' ', text)
                return text

            if isinstance(node, Tag):
                name = node.name.lower()

                # 图片：图文混排
                if name == 'img':
                    src = node.get('zoomfile') or node.get('file') or node.get('data-src') or node.get('src')
                    img_url = normalize_img_url(src)
                    if img_url:
                        if img_url not in seen_urls:
                            seen_urls.add(img_url)
                            images.append(img_url)
                        if IMAGE_MODE == 'text_only':
                            return f"\n\n[图片]({img_url})\n\n"
                        return f"\n\n![图片]({img_url})\n\n"
                    return ""

                # 块级换行元素
                if name in ['br']:
                    return "\n"
                if name in ['p', 'div', 'tr', 'table', 'tbody', 'blockquote', 'ul', 'ol', 'li']:
                    inner = ''.join(traverse(c) for c in node.children)
                    # 列表项前缀
                    if name == 'li':
                        inner = inner.strip()
                        if inner:
                            inner = f"- {inner}"
                    return f"{inner}\n"

                # 加粗/强调
                if name in ['strong', 'b'] or (name == 'font' and node.get('color')):
                    inner = ''.join(traverse(c) for c in node.children).strip()
                    return f"**{inner}**" if inner else ""

                # 链接
                if name == 'a':
                    href = node.get('href', '')
                    text = ''.join(traverse(c) for c in node.children).strip()
                    if not href:
                        return text
                    if not href.startswith(('http:', 'https:')):
                        href = urljoin(BASE_URL + '/', href)
                    return f"[{text}]({href})" if text else ""

                # 默认递归
                return ''.join(traverse(c) for c in node.children)

            return ""

        markdown_text = traverse(soup)
        # 清理空行
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
        markdown_text = markdown_text.strip()

        return markdown_text, images

    def _format_message(self, post_data: Dict, fid: int) -> str:
        """
        格式化推送消息为 Markdown
        
        Args:
            post_data: 帖子数据字典
            fid: 驿站ID
            
        Returns:
            Markdown 格式的消息
        """
        subject = post_data.get('subject', '无标题')
        author = post_data.get('author', '未知')
        time_str = post_data.get('time', '未知时间')
        content = post_data.get('content', '')
        images = post_data.get('images', [])
        url = post_data.get('url', '')
        
        # 控制内容长度：PREVIEW_LIMIT<=0 则不截断
        if PREVIEW_LIMIT > 0 and len(content) > PREVIEW_LIMIT:
            content_preview = content[:PREVIEW_LIMIT] + '...'
        else:
            content_preview = content
        
        lines: List[str] = []
        lines.append("## 📢 新动态提醒")
        lines.append("")
        # 标题可点击
        if url:
            lines.append(f"**标题**: [{subject}]({url})")
        else:
            lines.append(f"**标题**: {subject}")
        lines.append(f"**作者**: {author}")
        lines.append(f"**时间**: {time_str}")
        lines.append(f"**驿站**: #{fid}")
        lines.append("")
        lines.append("**内容**:")
        lines.append(content_preview if content_preview else "（无文本内容）")
        
        # 图片已在内容中图文混排，这里不再重复列出；仅在 direct 模式下追加防盗链提示
        if IMAGE_MODE == 'direct':
            lines.append("")
            lines.append("*注意：图片可能有防盗链，如无法显示请点击链接查看*")
        
        return "\n".join(lines)

    def send_dingtalk(self, message: str, post_data: Dict = None) -> bool:
        """
        发送消息到钉钉
        
        Args:
            message: Markdown 格式的消息
            
        Returns:
            是否发送成功
        """
        if not DINGTALK_WEBHOOK or DINGTALK_WEBHOOK == "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN":
            self.logger.warning("钉钉 Webhook 未配置，跳过推送")
            return False
        
        # 处理钉钉加签（如果配置了 DINGTALK_SECRET）
        webhook_url = DINGTALK_WEBHOOK
        if DINGTALK_SECRET:
            try:
                timestamp = str(round(time.time() * 1000))
                string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
                hmac_code = hmac.new(
                    DINGTALK_SECRET.encode('utf-8'),
                    string_to_sign.encode('utf-8'),
                    digestmod=hashlib.sha256
                ).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                delimiter = '&' if '?' in webhook_url else '?'
                webhook_url = f"{webhook_url}{delimiter}timestamp={timestamp}&sign={sign}"
                self.logger.debug("钉钉加签已生成并附加到 Webhook")
            except Exception as e:
                self.logger.error(f"生成钉钉加签失败: {e}")
                return False

        # 若配置了钉钉关键词，确保消息包含关键词（前缀添加）
        if DINGTALK_KEYWORD:
            message = f"{DINGTALK_KEYWORD} {message}"

        # 构建消息（actionCard，图片可直链展示）
        title = post_data.get('subject', 'Discuz 新动态') if post_data else 'Discuz 新动态'
        url = post_data.get('url', '') if post_data else ''

        # 使用 Markdown 保留图文原位（内容中已包含 ![图片](url)）
        markdown_body = f"### {title}\n\n{message}\n\n"
        if url:
            markdown_body += f"[🔗 查看原帖]({url})"

        action_card_payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": markdown_body,
                "singleTitle": "查看原帖" if url else "查看详情",
                "singleURL": url if url else "https://www.55188.com"
            }
        }
        
        try:
            response = requests.post(webhook_url, json=action_card_payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get('errcode') == 0:
                self.logger.info("钉钉推送成功")
                return True
            else:
                self.logger.error(f"钉钉推送失败: {result}")
                return False
        except Exception as e:
            self.logger.error(f"钉钉推送异常: {e}")
            return False

    def send_feishu(self, message: str, post_data: Dict = None) -> bool:
        """
        发送消息到飞书
        
        Args:
            message: Markdown 格式的消息
            post_data: 帖子数据（用于构建更丰富的卡片）
            
        Returns:
            是否发送成功
        """
        if not FEISHU_WEBHOOK or FEISHU_WEBHOOK == "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_TOKEN":
            self.logger.warning("飞书 Webhook 未配置，跳过推送")
            return False
        
        # 飞书 post 富文本：按原内容顺序插入文本与“图片链接”占位（无 image_key 时无法直显）
        subject = post_data.get('subject', '无标题') if post_data else '新动态'
        author = post_data.get('author', '未知') if post_data else ''
        time_str = post_data.get('time', '未知时间') if post_data else ''
        url = post_data.get('url', '') if post_data else ''
        content = post_data.get('content', '') if post_data else message

        # 截断正文（仅限文本），图片提取用完整正文，避免截断掉图片占位
        if PREVIEW_LIMIT > 0 and len(content) > PREVIEW_LIMIT:
            content_preview = content[:PREVIEW_LIMIT] + "..."
        else:
            content_preview = content
        full_content_for_images = content  # 保留全部文本用于提取图片占位

        # 将正文中的 ![xxx](url) 按顺序拆成文本 + 链接块
        import re
        pattern = re.compile(r'!\[.*?\]\((.*?)\)')
        parts = pattern.split(full_content_for_images)
        img_urls = pattern.findall(full_content_for_images)

        post_blocks = []
        # 标题行
        title_block = [{"tag": "a", "text": subject, "href": url}] if url else [{"tag": "text", "text": subject}]
        post_blocks.append(title_block)
        # 元信息
        post_blocks.append([{"tag": "text", "text": f"作者：{author}    时间：{time_str}"}])

        # 按顺序拼接文本（使用截断后的文本）和图片链接（保留全部图片）
        for i, text_part in enumerate(parts):
            text_part = text_part.strip()
            if text_part:
                # 对应截断后的文本片段
                truncated_segment = text_part
                if PREVIEW_LIMIT > 0 and len(truncated_segment) > PREVIEW_LIMIT:
                    truncated_segment = truncated_segment[:PREVIEW_LIMIT] + "..."
                post_blocks.append([{"tag": "text", "text": truncated_segment}])
            if i < len(img_urls):
                img = img_urls[i]
                post_blocks.append([{"tag": "a", "text": "🖼 图片", "href": img}])

        # 末尾追加原帖链接
        if url:
            post_blocks.append([{"tag": "a", "text": "🔗 查看原帖", "href": url}])

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📢 驿站新动态 | {subject}",
                        "content": post_blocks
                    }
                }
            }
        }
        
        try:
            response = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get('code') == 0:
                self.logger.info("飞书推送成功")
                return True
            else:
                self.logger.error(f"飞书推送失败: {result}")
                return False
        except Exception as e:
            self.logger.error(f"飞书推送异常: {e}")
            return False

    def _upload_images_to_feishu(self, image_urls: List[str]) -> List[str]:
        """
        下载图片并上传到飞书，返回 image_key 列表
        
        注意：此功能需要飞书 App ID 和 App Secret，配置较复杂
        如果未配置，将回退到直接链接模式
        
        Args:
            image_urls: 图片 URL 列表
            
        Returns:
            image_key 列表（用于飞书卡片）
        """
        # 注意：飞书图片上传需要 App ID 和 App Secret，这里先返回空列表
        # 如果需要实现，需要：
        # 1. 获取飞书 access_token
        # 2. 下载图片（带 Referer）
        # 3. 调用飞书图片上传 API
        # 4. 返回 image_key
        
        self.logger.debug("图片上传到飞书功能暂未实现，使用直接链接模式")
        return []
    
    def _process_new_posts(self, fid: int, livelastpost_data: Dict):
        """
        处理新发现的帖子
        
        Args:
            fid: 驿站ID
            livelastpost_data: livelastpost 接口返回的数据
        """
        fid_state = self.state.get(fid, {'last_pid': 0, 'last_tid': 0})
        last_pid = fid_state.get('last_pid', 0)
        new_pid = last_pid
        
        # 解析新帖子列表（注意：实际返回的是 'list' 字段，不是 'data'）
        posts = livelastpost_data.get('list', [])
        if not isinstance(posts, list):
            posts = []
        
        for post_item in posts:
            try:
                pid = post_item.get('pid')
                if not pid:
                    continue
                
                pid = int(pid)
                
                # 只处理比 last_pid 更大的新帖子
                if pid <= last_pid:
                    self.logger.debug(f"FID {fid}: PID {pid} 已处理过，跳过")
                    continue
                
                # 更新最大 PID
                if pid > new_pid:
                    new_pid = pid
                
                # 检查是否为"仅订阅用户可见"
                message_html = post_item.get('message', '')
                if '仅订阅用户可见' in message_html or 'need_follow_a' in message_html:
                    self.logger.debug(f"FID {fid}: PID {pid} 内容为'仅订阅用户可见'，跳过")
                    continue
                
                # 优化后的逻辑：优先尝试获取 TID，失败则直接使用 livelastpost 内容（不报错）
                # 这是正常情况，因为 livelastpost 返回的数据中可能不包含 TID
                tid = self._extract_tid_from_message(message_html)
                
                post_data = None
                
                if tid:
                    # 有 TID，尝试使用 Mobile API 获取完整内容
                    self.logger.debug(f"FID {fid}: 尝试使用 Mobile API 获取 TID {tid} PID {pid} 的详情")
                    thread_data = self._get_thread_detail(tid, pid)
                    
                    if thread_data:
                        # Mobile API 成功，提取内容
                        post_data = self._extract_post_content(thread_data, pid)
                        if post_data:
                            self.logger.debug(f"FID {fid}: 成功从 Mobile API 获取 PID {pid} 的内容")
                
                # 如果 Mobile API 失败或没有 TID，使用 livelastpost 的内容（回退方案）
                # 这是正常情况，不要报错
                if not post_data:
                    self.logger.debug(f"FID {fid}: 使用 livelastpost 返回的内容（PID {pid}）")
                    post_data = self._extract_from_livelastpost(post_item, fid)
                
                if not post_data:
                    self.logger.warning(f"FID {fid}: PID {pid} 无法提取内容，跳过")
                    continue
                
                # 格式化消息
                message = self._format_message(post_data, fid)
                
                # 推送（添加频率限制，防止触发 Webhook 限流）
                # 钉钉限制：每分钟20条消息；飞书也有类似限制
                # 在推送之间添加延时，避免瞬间爆发导致消息被丢弃
                self.send_dingtalk(message)
                time.sleep(1.5)  # 推送消息之间的延时（防止 Webhook 限流）
                self.send_feishu(message, post_data)
                time.sleep(1.5)  # 推送消息之间的延时（防止 Webhook 限流）
                
                # 更新状态
                if fid not in self.state:
                    self.state[fid] = {'last_pid': 0, 'last_tid': 0}
                self.state[fid]['last_pid'] = pid
                self._save_state()
                
                self.logger.info(f"FID {fid}: 已处理 PID {pid}")
                
                # 避免请求过快（API 请求之间的延时）
                time.sleep(2)
                
            except Exception as e:
                self.logger.error(f"处理帖子时出错: {e}", exc_info=True)
                continue
        
        # 更新最大 PID（即使某些帖子处理失败）
        if new_pid > last_pid:
            if fid not in self.state:
                self.state[fid] = {'last_pid': 0, 'last_tid': 0}
            self.state[fid]['last_pid'] = new_pid
            self._save_state()

    def _process_thread_list(self, fid: int, threads: List[Dict]):
        """
        处理列表页发现的帖子（按 TID 去重并只处理比 last_tid 更新的）
        """
        fid_state = self.state.get(fid, {'last_pid': 0, 'last_tid': 0})
        last_tid = fid_state.get('last_tid', 0)
        new_tid = last_tid

        # 列表页按时间倒序，倒序处理保证从旧到新，避免漏推
        for thread in sorted(threads, key=lambda x: x.get('tid', 0)):
            try:
                tid_int = int(thread.get('tid'))
            except ValueError:
                continue

            # 只处理比 last_tid 更新的帖子
            if tid_int <= last_tid:
                self.logger.debug(f"FID {fid}: TID {tid_int} 已处理过，跳过")
                continue

            self.logger.info(f"FID {fid}: 获取 TID {tid_int} 的详情（列表模式），锁帖: {thread.get('is_locked')}")
            thread_data = self._get_thread_detail(tid_int, target_pid=None)
            post_data = None

            # 尝试使用 Mobile API 内容
            if thread_data and isinstance(thread_data, dict) and thread_data.get('Variables'):
                variables = thread_data.get('Variables', {})
                post_list = variables.get('postlist', [])
                if post_list:
                    first_post = post_list[0]
                    pid = int(first_post.get('pid', 0)) if first_post.get('pid') else None
                    if pid:
                        post_data = self._extract_post_content(thread_data, pid)
                        if post_data:
                            self.logger.debug(f"FID {fid}: 成功从 Mobile API 获取 TID {tid_int} 的内容")

            # 如果 API 获取不到内容或被屏蔽，则走网页回退
            if not post_data:
                self.logger.debug(f"FID {fid}: 使用网页回退获取 TID {tid_int} 的内容")
                text_content, images = self._get_web_content_fallback(tid_int, fid_hint=fid)
                post_data = {
                    'subject': thread.get('title') or f"TID {tid_int}",
                    'author': thread.get('author') or '未知',
                    'author_id': '',
                    'time': thread.get('dateline') or '',
                    'content': text_content or '',
                    'images': images or [],
                    'url': f"{BASE_URL}/thread-{tid_int}-1-1.html",
                    'pid': '',
                    'tid': tid_int
                }

            # 格式化消息
            message = self._format_message(post_data, fid)

            # 推送（频率限制）
            self.send_dingtalk(message)
            time.sleep(1.5)
            self.send_feishu(message, post_data)
            time.sleep(1.5)

            # 更新状态
            if fid not in self.state:
                self.state[fid] = {'last_pid': 0, 'last_tid': 0}
            self.state[fid]['last_tid'] = tid_int
            new_tid = max(new_tid, tid_int)
            self._save_state()

            self.logger.info(f"FID {fid}: 已处理 TID {tid_int}")
            time.sleep(2)

        # 更新最大 TID
        if new_tid > last_tid:
            if fid not in self.state:
                self.state[fid] = {'last_pid': 0, 'last_tid': 0}
            self.state[fid]['last_tid'] = new_tid
            self._save_state()

    def monitor_fid(self, fid: int):
        """
        监控单个驿站（列表页解析模式）
        
        Args:
            fid: 驿站ID
        """
        fid_state = self.state.get(fid, {'last_pid': 0, 'last_tid': 0})
        last_pid = fid_state.get('last_pid', 0)
        last_tid = fid_state.get('last_tid', 0)
        self.logger.info(f"开始监控 FID {fid}，当前 last_pid: {last_pid}, last_tid: {last_tid}")

        # 使用列表页解析，精准获取当前驿站帖子
        threads = self._get_thread_list(fid, pages=LIST_PAGES)
        if threads:
            self._process_thread_list(fid, threads)
        else:
            self.logger.debug(f"FID {fid}: 列表页未发现新帖（或请求失败）")

    def run(self):
        """主循环"""
        self.logger.info("=" * 50)
        self.logger.info("DiscuzSentinel 启动")
        self.logger.info(f"监控驿站: {TARGET_FIDS}")
        self.logger.info("=" * 50)
        
        while True:
            try:
                for fid in TARGET_FIDS:
                    try:
                        self.monitor_fid(fid)
                    except Exception as e:
                        self.logger.error(f"监控 FID {fid} 时出错: {e}")
                    
                    # 驿站之间稍作间隔
                    time.sleep(3)
                
                # 随机休眠 30-60 秒
                sleep_time = random.randint(30, 60)
                self.logger.info(f"本轮监控完成，休眠 {sleep_time} 秒...")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                self.logger.info("收到中断信号，正在退出...")
                break
            except Exception as e:
                self.logger.error(f"主循环异常: {e}")
                time.sleep(60)  # 出错后等待1分钟再继续


# ==================== 主程序入口 ====================

if __name__ == "__main__":
    sentinel = DiscuzSentinel()
    sentinel.run()

