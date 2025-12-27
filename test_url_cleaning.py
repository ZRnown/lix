#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试URL清洗功能
"""

def test_url_cleaning():
    """测试URL清洗功能"""
    
    # 模拟原始URL
    test_urls = [
        "https://www.55188.com/data/attachment/forum/202512/27/095815qrhb04fr47mhr50l.jpg?imageMogr2/thumbnail/1920x1280%3E?imageMogr2/thumbnail/815x1024%3E",
        "https://www.55188.com/data/attachment/forum/202512/27/095815qrhb04fr47mhr50l.jpg",
        "https://www.55188.com/data/attachment/forum/202512/27/095815qrhb04fr47mhr50l.jpg?param=value",
        "https://www.55188.com/data/attachment/forum/202512/27/095815qrhb04fr47mhr50l.jpg?imageMogr2/thumbnail/1920x1280%3E",
    ]
    
    print("URL清洗测试:")
    print("=" * 60)
    
    for original_url in test_urls:
        # 模拟清洗逻辑
        if '?' in original_url:
            cleaned_url = original_url.split('?')[0]
        else:
            cleaned_url = original_url
            
        print(f"原始: {original_url}")
        print(f"清洗: {cleaned_url}")
        print("-" * 40)

if __name__ == "__main__":
    test_url_cleaning()
