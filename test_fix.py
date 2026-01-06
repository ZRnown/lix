#!/usr/bin/env python3
"""
测试修复的URL清洗逻辑
"""

def test_url_cleaning():
    """测试URL清洗逻辑"""

    # 测试用例
    test_cases = [
        # (原始URL, 期望的处理后URL)
        ("https://www.55188.com/forum.php?mod=image&aid=12345&w=500&h=300", "https://www.55188.com/forum.php?mod=image&aid=12345&w=500&h=300"),  # 不应该截断
        ("https://www.55188.com/data/attachment/forum/202401/01/12345.jpg?imageMogr2/thumbnail/800x", "https://www.55188.com/data/attachment/forum/202401/01/12345.jpg"),  # 应该截断
        ("https://www.55188.com/static/image/smiley/default/smile.gif", "https://www.55188.com/static/image/smiley/default/smile.gif"),  # 无参数
        ("https://www.55188.com/data/attachment/forum/202401/01/12345.png>", "https://www.55188.com/data/attachment/forum/202401/01/12345.png"),  # 去除末尾>
    ]

    for original_url, expected_url in test_cases:
        # 模拟修复后的逻辑
        src = original_url

        # 修复：去除末尾可能存在的错误符号 '>'
        src = src.strip('>')

        # 修复：只有当不是 Discuz 动态 PHP 链接时，才去除 ? 后面的参数
        if '?' in src and 'forum.php' not in src and 'mod=image' not in src:
            src = src.split('?')[0]

        result = src
        status = "✅" if result == expected_url else "❌"
        print(f"{status} 原始: {original_url}")
        print(f"   结果: {result}")
        print(f"   期望: {expected_url}")
        if result != expected_url:
            print("   *** 不匹配 ***")
        print()

if __name__ == "__main__":
    test_url_cleaning()
