#!/usr/bin/env python3
"""
测试token计数功能
"""

from model.factory import chat_model
from utils.token_counter import token_counter

def test_token_counting():
    """测试token计数"""
    print("🧪 测试Token计数功能")
    print("=" * 50)

    # 测试前重置会话统计
    token_counter.reset_session()
    print("✅ 会话统计已重置")

    # 测试模型调用
    print("\n📤 发送测试消息...")
    try:
        response = chat_model.invoke("你好，请介绍一下自己")
        print(f"📥 模型响应: {response.content[:100]}...")

        # 检查token统计
        session_stats = token_counter.get_session_stats()
        print("\n📊 当前会话Token统计:")
        print(f"  输入Token: {session_stats['input_tokens']}")
        print(f"  输出Token: {session_stats['output_tokens']}")
        print(f"  总Token数: {session_stats['total_tokens']}")
        print(f"  预估费用: ¥{session_stats['total_cost']:.4f}")

        # 检查历史记录
        history = token_counter.get_history(limit=3)
        if history:
            print("\n📋 最近Token使用记录:")
            for i, record in enumerate(history, 1):
                print(f"  {i}. {record['timestamp']} | Input: {record['input']} | Output: {record['output']} | Total: {record['total']}")

        print("\n✅ Token计数功能测试完成！")

    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_token_counting()