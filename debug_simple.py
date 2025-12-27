#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的图床诊断脚本
"""

import requests
import json

def test_upload_minimal():
    """使用最小的PNG数据测试上传"""
    # 这是最小的有效PNG文件数据（1x1像素，纯色）
    minimal_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01]\xdbF\x0e\x00\x00\x00\x00IEND\xaeB`\x82'
    
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
    
    files = {'image': ('test.png', minimal_png, 'image/png')}
    
    print("🔍 测试最小PNG图片上传...")
    print(f"图片大小: {len(minimal_png)} bytes")
    
    try:
        res = requests.post(upload_url, files=files, headers=headers, timeout=30, verify=False)
        
        print(f"HTTP状态码: {res.status_code}")
        
        if res.status_code == 200:
            try:
                data = res.json()
                print(f"响应数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
                
                if data.get('code') == 200:
                    print("✅ 上传成功")
                    return True
                else:
                    print(f"❌ API错误: {data}")
            except:
                print(f"❌ 非JSON响应: {res.text[:200]}")
        else:
            print(f"❌ HTTP错误: {res.status_code}")
            print(f"响应内容: {res.text[:200]}")
            
    except Exception as e:
        print(f"❌ 异常: {e}")
    
    return False

def analyze_problem():
    """分析可能的问题"""
    print("\n🔍 问题分析:")
    print("1. 图床服务器可能更改了验证规则")
    print("2. 图片文件在下载过程中损坏")
    print("3. 并发上传导致服务器拒绝")
    print("4. 图片格式或内容不符合要求")
    
    print("\n💡 建议解决方案:")
    print("1. 检查图片下载是否完整")
    print("2. 添加图片格式验证")
    print("3. 实现备用图床")
    print("4. 减少并发上传数量")

if __name__ == "__main__":
    print("开始诊断图床问题...")
    success = test_upload_minimal()
    analyze_problem()
