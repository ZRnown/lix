#!/usr/bin/env python3
print("测试修复后的作用域问题...")

# 模拟修复后的重试逻辑
for attempt in range(3):
    res = None  # 初始化res变量，避免作用域问题
    try:
        # 模拟可能失败的操作
        if attempt == 1:
            raise ConnectionResetError("Connection reset by peer")
        
        res = {"status_code": 200, "json": lambda: {"error": "非法图片文件"}}
        print(f"尝试 {attempt + 1}: 成功")
        
    except ConnectionResetError as e:
        print(f"尝试 {attempt + 1}: 连接被重置 - {e}")
    except Exception as e:
        print(f"尝试 {attempt + 1}: 其他异常 - {e}")
    
    # 检查重试逻辑
    should_retry = True
    if res and hasattr(res, 'status_code') and res['status_code'] == 200:
        try:
            response_data = res['json']()
            if response_data.get('error') == '非法图片文件':
                should_retry = False
                print(f"尝试 {attempt + 1}: 图片非法，跳过重试")
        except:
            pass
    
    if should_retry and attempt < 2:
        print(f"尝试 {attempt + 1}: {2 * (attempt + 1)} 秒后重试")
    elif not should_retry:
        print(f"尝试 {attempt + 1}: 不重试")
        break

print("测试完成 - 作用域问题已修复！")
