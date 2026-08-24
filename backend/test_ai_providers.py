"""
测试各个AI Provider的连接性和功能
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.ai_gateway import AIGateway


async def test_chat(gateway: AIGateway, provider: str):
    """测试对话功能"""
    print(f"\n{'='*60}")
    print(f"测试 {provider} - Chat 接口")
    print(f"{'='*60}")

    try:
        response = await gateway.chat(
            messages=[
                {"role": "user", "content": "你好，请用一句话介绍你自己"}
            ],
            provider=provider,
            temperature=0.7
        )

        print(f"✅ 调用成功")
        print(f"响应内容: {response['content'][:100]}...")
        print(f"Token使用: {response['usage']}")
        return True

    except Exception as e:
        print(f"❌ 调用失败: {str(e)}")
        return False


async def test_embed(gateway: AIGateway, provider: str):
    """测试嵌入功能"""
    print(f"\n{'='*60}")
    print(f"测试 {provider} - Embed 接口")
    print(f"{'='*60}")

    try:
        embeddings = await gateway.embed(
            texts=["这是一个测试文本", "另一个测试文本"],
            provider=provider
        )

        print(f"✅ 调用成功")
        print(f"嵌入维度: {len(embeddings[0]) if embeddings else 0}")
        print(f"嵌入数量: {len(embeddings)}")
        return True

    except Exception as e:
        print(f"❌ 调用失败: {str(e)}")
        return False


async def main():
    """主测试函数"""
    print("="*60)
    print("AI Provider 连接测试")
    print("="*60)

    # 检查环境变量
    print("\n1. 检查环境变量配置:")
    env_vars = {
        "GLM-4": "GLM4_API_KEY",
        "千问": "QWEN_API_KEY",
        "DeepSeek": "DEEPSEEK_API_KEY",
        "Claude": "CLAUDE_API_KEY"
    }

    configured_providers = []
    for provider, env_key in env_vars.items():
        value = os.getenv(env_key)
        if value:
            print(f"  ✅ {provider}: {env_key} 已配置 (长度: {len(value)})")
            configured_providers.append(provider)
        else:
            print(f"  ❌ {provider}: {env_key} 未配置")

    if not configured_providers:
        print("\n⚠️  没有配置任何API密钥，无法测试")
        print("\n请在环境变量中配置至少一个API密钥:")
        print("  - GLM4_API_KEY")
        print("  - QWEN_API_KEY")
        print("  - DEEPSEEK_API_KEY")
        print("  - CLAUDE_API_KEY")
        return

    # 初始化网关
    gateway = AIGateway()

    # 测试结果统计
    results = {
        "chat": {},
        "embed": {}
    }

    # 测试每个已配置的provider
    print(f"\n2. 开始测试已配置的provider:")

    for provider in configured_providers:
        # 测试Chat接口
        results["chat"][provider] = await test_chat(gateway, provider)
        await asyncio.sleep(1)  # 避免请求过快

        # 测试Embed接口
        results["embed"][provider] = await test_embed(gateway, provider)
        await asyncio.sleep(1)

    # 输出汇总
    print(f"\n{'='*60}")
    print("测试结果汇总")
    print(f"{'='*60}")

    print("\nChat接口:")
    for provider, success in results["chat"].items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {provider}: {status}")

    print("\nEmbed接口:")
    for provider, success in results["embed"].items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {provider}: {status}")

    # 总体评估
    total_tests = len(results["chat"]) + len(results["embed"])
    passed_tests = sum(results["chat"].values()) + sum(results["embed"].values())

    print(f"\n总计: {passed_tests}/{total_tests} 个测试通过")

    if passed_tests == total_tests:
        print("\n🎉 所有测试通过！AI网关工作正常。")
    elif passed_tests > 0:
        print("\n⚠️  部分测试通过，请检查失败的provider配置。")
    else:
        print("\n❌ 所有测试失败，请检查网络连接和API密钥配置。")


if __name__ == "__main__":
    asyncio.run(main())
