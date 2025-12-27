#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断图床"非法图片文件"错误的脚本
"""

import requests
import time
import random
import json
from PIL import Image
import io

def create_test_images():
    """创建不同类型的测试图片"""
    images = {}
    
    # 1. 创建一个简单的PNG图片
    img = Image.new('RGB', (100, 100), color='red')
    png_buffer = io.BytesIO()
    img.save(png_buffer, format='PNG')
    images['png'] = png_buffer.getvalue()
    
    # 2. 创建一个JPEG图片
    jpeg_buffer = io.BytesIO()
    img.save(jpeg_buffer, format='JPEG')
    images['jpeg'] = jpeg_buffer.getvalue()
    
    # 3. 创建一个GIF图片
    gif_buffer = io.BytesIO()
    img.save(gif_buffer, format='GIF')
    images['gif'] = gif_buffer.getvalue()
    
    # 4. 创建一个1x1像素的最小PNG
    tiny_img = Image.new('RGB', (1, 1), color='blue')
    tiny_buffer = io.BytesIO()
    tiny_img.save(tiny_buffer, format='PNG')
    images['tiny_png'] = tiny_buffer.getvalue()
    
    return images

def test_image_upload(image_data, image_type, filename):
    """测试上传特定类型的图片"""
    upload_url = "http://frp-cup.com:12245/upload/upload.html"
    
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Origin': 'http://frp-cup.com:12245',
        'Referer': 'http://frp-cup.com:12245/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    mime_types = {
        'png': 'image/png',
        'jpeg': 'image/jpeg', 
        'gif': 'image/gif'
    }
    
    files = {'image': (filename, image_data, mime_types.get(image_type, 'image/png'))}
    
    print(f"\n🔍 测试上传 {image_type} 图片: {filename} (大小: {len(image_data)} bytes)")
    
    try:
        res = requests.post(upload_url, files=files, headers=headers, timeout=30, verify=False)
        
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
                        return True
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
            
    except Exception as e:
        print(f"❌ 上传异常: {e}")
    
    return False

def analyze_discuz_image():
    """分析真实的Discuz图片数据"""
    print("\n🔬 分析可能的问题原因:")
    print("1. 图片文件损坏或格式异常")
    print("2. 图片太大（图床可能有限制）")
    print("3. 图片包含不支持的元数据")
    print("4. 服务器验证规则改变")
    print("5. 并发上传过多导致服务器拒绝")
    
    print("\n💡 建议解决方案:")
    print("1. 检查图片是否完整下载")
    print("2. 考虑添加图片大小检查")
    print("3. 实现备用图床方案")
    print("4. 添加图片预处理（压缩、格式转换）")

if __name__ == "__main__":
    print("开始诊断图床'非法图片文件'错误...")
    
    # 创建测试图片
    test_images = create_test_images()
    
    # 测试不同类型的图片
    success_count = 0
    for img_type, img_data in test_images.items():
        filename = f"test_{int(time.time())}_{random.randint(100,999)}.{img_type}"
        if test_image_upload(img_data, img_type, filename):
            success_count += 1
        time.sleep(1)  # 避免请求过快
    
    print(f"\n📊 测试结果: {success_count}/{len(test_images)} 种图片类型上传成功")
    
    if success_count == 0:
        print("❌ 所有测试图片都上传失败，图床服务器可能有问题")
    elif success_count < len(test_images):
        print("⚠️ 部分图片类型上传失败，可能存在格式限制")
    else:
        print("✅ 所有测试图片上传成功，问题可能在于源图片质量")
    
    analyze_discuz_image()
