#!/usr/bin/env python3
"""
Grok Twitter Search - 优化版
1. 精简 prompt 减少 input tokens
2. 正确的 xAI Responses API 格式
3. 调用后报告 token 消耗
4. 智能解析 Grok 返回的推文文本
"""

import os
import sys
import json
import argparse
import httpx
import re

# 全局复用 HTTP 客户端
_http_client = None

def get_client(proxy: str = None) -> httpx.Client:
    """获取或初始化全局 HTTP Client"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0, read=60.0))
    return _http_client


def parse_tweets_from_text(text: str, annotations: list) -> list:
    """从 Grok 返回的文本中提取结构化推文数据"""
    tweets = []
    
    # 匹配推文模式：编号. **@用户名** (日期): "内容"
    # 示例：1. **@BitcoinJunkies** (Feb 27, 2026): "What's this pattern called?"
    pattern = r'(\d+)\.\s*\*\*@([^*]+)\*\*\s*\(([^)]+)\):\s*"([^"]+)"'
    
    matches = re.findall(pattern, text)
    
    # 构建 URL 映射（从 annotations 中提取）
    url_map = {}
    for ann in annotations:
        if ann.get("type") == "url_citation":
            title = ann.get("title", "")
            url = ann.get("url", "")
            if title and url:
                url_map[title] = url
    
    for idx, (num, author, date, content) in enumerate(matches):
        tweet_url = url_map.get(str(idx + 1), "")
        tweets.append({
            "author": f"@{author.strip()}",
            "content": content.strip(),
            "timestamp": date.strip(),
            "likes": 0,
            "retweets": 0,
            "url": tweet_url
        })
    
    # 如果没有提取到结构化数据，返回整个文本作为摘要
    if not tweets and text.strip():
        tweets.append({
            "author": "Grok Summary",
            "content": text[:800] + "..." if len(text) > 800 else text,
            "timestamp": "Now",
            "likes": 0,
            "retweets": 0,
            "url": ""
        })
    
    return tweets


def search_twitter(
    query: str, 
    api_key: str, 
    api_base: str = "https://api.x.ai/v1", 
    max_results: int = 10,
    proxy: str = None,
    analyze: bool = False
) -> dict:
    """调用 xAI API，使用原生工具返回机制"""
    
    url = f"{api_base.rstrip('/')}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 模型选择：只有 reasoning 模型支持 x_search 工具
    model = "grok-4-1-fast-reasoning"
    
    # 精简的 payload，减少 input tokens
    payload = {
        "model": model,
        "input": f"Search Twitter for: {query}. Return up to {max_results} tweets.",
        "tools": [{"type": "x_search"}],
        "temperature": 0.0
    }

    try:
        client = get_client(proxy)
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        
        # 初始化结果
        result = {
            "status": "success",
            "query": query,
            "tweets": [],
            "model_used": model,
            "usage": {},
            "cost_report": ""
        }
        
        # 提取 usage 信息
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0) or (input_tokens + output_tokens)
        x_search_calls = usage.get("x_search_calls", 0)
        
        result["usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "x_search_calls": x_search_calls
        }
        
        # 生成成本报告
        input_cost = (input_tokens / 1_000_000) * 0.20
        output_cost = (output_tokens / 1_000_000) * 0.50
        total_cost = input_cost + output_cost
        
        result["cost_report"] = (
            f"📊 Token 消耗报告:\n"
            f"   Input tokens:  {input_tokens:,}\n"
            f"   Output tokens: {output_tokens:,}\n"
            f"   Total tokens:  {total_tokens:,}\n"
            f"   X Search calls: {x_search_calls}\n"
            f"   💰 预估成本: ${total_cost:.4f} (${total_cost*1000:.2f}/千次)"
        )
        
        # 解析推文数据
        tweets = []
        output_list = data.get("output", [])
        
        for response_item in output_list:
            if not isinstance(response_item, dict):
                continue
            
            # 策略 1: 从 message 内容中解析（主要来源）
            if response_item.get("type") == "message":
                message = response_item.get("message", response_item)
                content = message.get("content", "")
                
                # 如果 content 是列表（新的 API 格式）
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "output_text":
                            text = c.get("text", "")
                            annotations = c.get("annotations", [])
                            
                            # 从文本中提取推文
                            extracted = parse_tweets_from_text(text, annotations)
                            tweets.extend(extracted)
                
                # 如果 content 是字符串（旧的 API 格式）
                elif isinstance(content, str) and content.strip():
                    tweets.append({
                        "author": "Grok Summary",
                        "content": content[:500] + "..." if len(content) > 500 else content,
                        "timestamp": "Now",
                        "likes": 0,
                        "retweets": 0,
                        "url": ""
                    })
        
        result["tweets"] = tweets[:max_results]
        
        # 将 token 消耗报告添加到结果中
        result["token_report"] = result["cost_report"]
        
        # 打印到 stdout 确保 OpenClaw 能看到
        print(result["cost_report"], flush=True)
        
        return result

    except httpx.HTTPStatusError as e:
        error_msg = f"API 错误: {e.response.status_code} - {e.response.text[:200]}"
        print(f"❌ {error_msg}", file=sys.stderr)
        return {"status": "error", "message": error_msg}
    except httpx.RequestError as e:
        error_msg = f"网络/代理错误: {e}"
        print(f"❌ {error_msg}", file=sys.stderr)
        return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"未知错误: {e}"
        print(f"❌ {error_msg}", file=sys.stderr)
        return {"status": "error", "message": error_msg}


def run_interactive_mode(api_key: str, default_proxy: str):
    """纯数字菜单交互模式"""
    while True:
        print("\n" + "="*40)
        print("  🐦 Grok Twitter 搜索")
        print("="*40)
        print(f"当前代理: {default_proxy or '直连'}")
        print("1. 极速检索")
        print("2. 深度分析")
        print("0. 退出")
        print("="*40)
        
        try:
            choice = input("请选择: ").strip()
            if choice == '0':
                break
            elif choice in ('1', '2'):
                query = input("\n搜索关键词: ").strip()
                if not query:
                    continue
                
                print(f"\n🔍 搜索中...")
                res = search_twitter(
                    query=query, 
                    api_key=api_key, 
                    proxy=default_proxy, 
                    analyze=(choice == '2')
                )
                
                # 打印结果
                output = {k: v for k, v in res.items() if k != "cost_report"}
                print(json.dumps(output, ensure_ascii=False, indent=2))
            else:
                print("[!] 无效输入")
        except KeyboardInterrupt:
            print("\n👋 再见")
            break
        except Exception as e:
            print(f"\n[!] 错误: {e}")


def main():
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Grok Twitter Search")
        parser.add_argument("--query", required=True, help="搜索查询")
        parser.add_argument("--api-key", help="Grok API Key")
        parser.add_argument("--api-base", default="https://api.x.ai/v1")
        parser.add_argument("--max-results", type=int, default=10)
        parser.add_argument("--proxy", help="SOCKS5 代理")
        parser.add_argument("--analyze", action="store_true", help="启用推理模式")
        
        args = parser.parse_args()
        
        api_key = args.api_key or os.environ.get("GROK_API_KEY")
        if not api_key:
            print(json.dumps({"status": "error", "message": "缺少 API Key"}))
            sys.exit(1)
            
        proxy = args.proxy or os.environ.get("SOCKS5_PROXY")
        
        result = search_twitter(
            args.query, api_key, args.api_base, 
            args.max_results, proxy, args.analyze
        )
        
        # 输出结果
        output = {k: v for k, v in result.items() if k != "cost_report"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        api_key = os.environ.get("GROK_API_KEY")
        if not api_key:
            print("[!] 未设置 GROK_API_KEY")
            sys.exit(1)
        proxy = os.environ.get("SOCKS5_PROXY")
        run_interactive_mode(api_key, proxy)


if __name__ == "__main__":
    main()
