#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试关键语法是否正确
"""

def test_basic_syntax():
    """测试基本的语法结构"""
    
    # 测试for循环和try-except
    for attempt in range(3):
        res = None  # 初始化变量
        try:
            # 模拟网络请求
            if attempt == 1:
                raise ConnectionResetError("Connection reset by peer")
            res = {"status_code": 200}
            
            if res["status_code"] == 200:
                try:
                    data = {"code": 200, "data": {"url": "http://example.com"}}
                    if data.get('code') == 200:
                        return "success"
                except:
                    pass
            else:
                print("HTTP error")
                
        except ConnectionResetError as e:
            print(f"Connection reset: {e}")
        except Exception as e:
            print(f"Exception: {e}")
        
        # 检查是否应该重试
        should_retry = True
        if res and res.get('status_code') == 200:
            try:
                response_data = {"error": "非法图片文件"}
                if response_data.get('error') == '非法图片文件':
                    should_retry = False
            except:
                pass
        
        if should_retry and attempt < 2:
            print(f"Retry after delay")
        elif not should_retry:
            break
    
    return "completed"

if __name__ == "__main__":
    result = test_basic_syntax()
    print(f"测试结果: {result}")
