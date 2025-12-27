#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自建图床上传功能
"""

import requests
import time
import random

def test_image_upload():
    '''测试图床上传功能'''
    # 模拟一个小的测试图片（1x1像素PNG）
    test_image_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01]\xdbF\x0e\x00\x00\x00\x00IEND\xaeB`\x82'
    
    filename = f'test_{int(time.time())}_{random.randint(100,999)}.png'
    
    # 自建图床上传（带重试机制）
    for attempt in range(5):  # 最多重试5次
        try:
            upload_url = "http://frp-cup.com:12245/upload/upload.html"

            # 构建multipart/form-data
            files = {'image': (filename, test_image_data, 'image/png')}

            # 设置请求头
            headers = {
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-CN;q=0.7,zh;q=0.6',
                'Connection': 'keep-alive',
                'Origin': 'http://frp-cup.com:12245',
                'Referer': 'http://frp-cup.com:12245/',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'X-Requested-With': 'XMLHttpRequest'
            }

            print(f'[图床] 尝试上传 {filename} (尝试 {attempt + 1}/5)')

            # 发送上传请求
            upload_timeout = 90 if attempt == 0 else 60  # 第一次尝试90秒，后续60秒
            res = requests.post(upload_url, files=files, headers=headers, timeout=upload_timeout, verify=False)

            print(f'[图床] HTTP响应码: {res.status_code}')
            
            if res.status_code == 200:
                try:
                    data = res.json()
                    print(f'[图床] 响应数据: {data}')
                    if data.get('code') == 200 and 'data' in data:
                        img_url_result = data['data'].get('url')
                        if img_url_result:
                            final_url = img_url_result.replace('\\/', '/')
                            print(f'✅ [图床] 上传成功: {final_url}')
                            return True
                        else:
                            print(f'[图床] 响应中没有URL: {data}')
                    else:
                        print(f'[图床] API响应错误: {data}')
                except Exception as e:
                    print(f'[图床] 解析响应失败: {e}')
                    print(f'[图床] 原始响应: {res.text[:200]}')
            else:
                print(f'[图床] HTTP {res.status_code} 错误')

        except requests.exceptions.Timeout as e:
            print(f'[图床] 请求超时 ({upload_timeout}s) (尝试 {attempt + 1}/5): {e}')
        except requests.exceptions.ConnectionError as e:
            if "RemoteDisconnected" in str(e) or "Connection aborted" in str(e):
                print(f'[图床] 连接被远程端断开 (尝试 {attempt + 1}/5): {e}')
            else:
                print(f'[图床] 连接错误 (尝试 {attempt + 1}/5): {e}')
        except Exception as e:
            print(f'[图床] 未知异常 (尝试 {attempt + 1}/5): {e}')

        # 如果不是最后一次尝试，等待后重试
        if attempt < 4:
            retry_delay = 3 * (attempt + 1)  # 3秒, 6秒, 9秒, 12秒
            print(f'[图床] {retry_delay} 秒后重试...')
            time.sleep(retry_delay)

    print('[图床] 上传失败，已达到最大重试次数')
    return False

if __name__ == "__main__":
    print('开始测试自建图床上传功能...')
    success = test_image_upload()
    print(f'测试结果: {"成功" if success else "失败"}')
