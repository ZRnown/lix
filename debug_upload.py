#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试图床上传问题的脚本
"""

import requests
import time
import random
import json

def test_upload_with_different_headers():
    '''测试不同请求头配置的图床上传'''
    
    # 创建测试图片数据
    test_image_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01]\xdbF\x0e\x00\x00\x00\x00IEND\xaeB`\x82'
    filename = f'test_{int(time.time())}_{random.randint(100,999)}.png'
    
    upload_url = "http://frp-cup.com:12245/upload/upload.html"
    files = {'image': (filename, test_image_data, 'image/png')}
    
    # 测试不同的请求头配置
    header_configs = [
        {
            'name': '原始配置',
            'headers': {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'Connection': 'keep-alive',
                'Origin': 'http://frp-cup.com:12245',
                'Referer': 'http://frp-cup.com:12245/',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'X-Requested-With': 'XMLHttpRequest'
            }
        },
        {
            'name': '简化的请求头',
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Origin': 'http://frp-cup.com:12245',
                'Referer': 'http://frp-cup.com:12245/'
            }
        },
        {
            'name': '更简化的请求头',
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        },
        {
            'name': '无自定义请求头',
            'headers': {}
        }
    ]
    
    print("开始测试不同的请求头配置...")
    print("=" * 60)
    
    for config in header_configs:
        print(f"\n🔍 测试配置: {config['name']}")
        print(f"请求头: {json.dumps(config['headers'], indent=2, ensure_ascii=False)}")
        
        try:
            res = requests.post(upload_url, files=files, headers=config['headers'], timeout=30, verify=False)
            
            print(f"HTTP状态码: {res.status_code}")
            print(f"响应头: {dict(res.headers)}")
            
            if res.status_code == 200:
                try:
                    data = res.json()
                    print(f"响应数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
                    
                    if data.get('code') == 200 and 'data' in data:
                        img_url_result = data['data'].get('url')
                        if img_url_result:
                            final_url = img_url_result.replace('\\/', '/')
                            print(f"✅ 上传成功: {final_url}")
                        else:
                            print("❌ 响应中没有URL")
                    else:
                        print(f"❌ API响应错误: {data}")
                        
                except json.JSONDecodeError as e:
                    print(f"❌ 响应不是有效JSON: {e}")
                    print(f"原始响应内容: {res.text[:500]}")
            else:
                print(f"❌ HTTP错误: {res.status_code}")
                print(f"响应内容: {res.text[:500]}")
                
        except requests.exceptions.ConnectionError as e:
            if "RemoteDisconnected" in str(e) or "Connection aborted" in str(e):
                print(f"❌ 连接被服务器断开: {e}")
            else:
                print(f"❌ 连接错误: {e}")
        except requests.exceptions.Timeout as e:
            print(f"❌ 请求超时: {e}")
        except Exception as e:
            print(f"❌ 其他异常: {e}")
        
        print("-" * 40)
        time.sleep(2)  # 请求间隔

if __name__ == "__main__":
    test_upload_with_different_headers()
