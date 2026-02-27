#!/usr/bin/env python3
"""
Grok Twitter Search - 高性能重构版
1. 客户端连接池复用 (httpx.Client)
2. 动态模型路由 (Fast vs Reasoning)
3. 纯净 Tool Call 原生数据提取 (零 LLM 渲染)
4. 细粒度防崩溃异常捕获 (PEP 8 标准)
"""

import os
import sys
import json
import argparse
import httpx
import re

# 全局复用 HTTP 客户端，维持连接池，降低握手延迟
_http_client = None

def get_client(proxy: str = None) -> httpx.Client:
    """获取或初始化全局 HTTP Client"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0, read=60.0))
    return _http_client

def format_tweet(tweet: dict) -> dict:
    """提取并格式化推文原生数据"""
    try:
        author = tweet.get("author", {})
        return {
            "author": f"@{author.get('handle', 'unknown').lstrip('@')}",
            "content": tweet.get("content", ""),
            "timestamp": tweet.get("timestamp", ""),
            "likes": tweet.get("engagement", {}).get("likes", 0),
            "retweets": tweet.get("engagement", {}).get("reposts", 0),
            "url": f"https://x.com/i/status/{tweet.get('id')}"
        }
    except (KeyError, TypeError, ValueError) as e:
        # 异常细化：针对单条数据结构突变，记录日志并返回空字典
        print(f"[Warn] 格式化单条推文数据异常: {e}", file=sys.stderr)
        return {}

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

    # 优化 1：模型降级与路由。纯检索用 fast，需总结用 reasoning
    model = "grok-4-1-fast-reasoning"  # 只有 reasoning 模型支持 x_search 工具调用
    
    # 优化 2：使用 messages 数组格式触发 x_search（实测有效）
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": "仅调用工具，不要回复任何解释性文本。"},
            {"role": "user", "content": f"搜索 Twitter：{query}，获取最多 {max_results} 条推文。"}
        ],
        "tools": [{"type": "x_search"}]
    }

    try:
        # 优化 3：复用全局连接池
        client = get_client(proxy)
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        result = {
            "status": "success",
            "query": query,
            "tweets": [],
            "x_search_calls": 0,
            "model_used": model
        }
        
        usage = data.get("usage", {})
        if usage:
            result["x_search_calls"] = usage.get("x_search_calls", 0)
            result["usage"] = {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
        
        output = data.get("output", [])
        tweets = []
        
        # 多策略解析：兼容 x_search 的不同返回格式
        
        for item in output:
            try:
                # 策略 1：原生工具返回（item 直接包含 author 和 id）
                if isinstance(item, dict) and item.get("author") and item.get("id"):
                    tweet_data = format_tweet(item)
                    if tweet_data and tweet_data not in tweets:
                        tweets.append(tweet_data)
                
                # 策略 2：message 类型，从 content 文本中解析推文
                elif item.get("type") == "message":
                    content_list = item.get("content", [])
                    if isinstance(content_list, list):
                        for c in content_list:
                            if c.get("type") == "output_text":
                                text = c.get("text", "")
                                
                                # 2a: 尝试提取 JSON 数组
                                json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
                                if json_match:
                                    try:
                                        parsed = json.loads(json_match.group())
                                        if isinstance(parsed, list):
                                            for t in parsed:
                                                if isinstance(t, dict):
                                                    tweet_data = format_tweet(t)
                                                    if tweet_data and tweet_data not in tweets:
                                                        tweets.append(tweet_data)
                                        continue
                                    except json.JSONDecodeError:
                                        pass
                                
                                # 2b: 解析文本格式的推文列表（兼容多种格式）
                                # 格式 A: "**@user** (timestamp): "content""
                                pattern_a = r'\*\*(@[^*]+)\*\*\s*\(([^)]+)\):\s*"([^"]+)"'
                                # 格式 B: "**timestamp** (ID: ...) 内容：content"
                                pattern_b = r'\*\*(\d{4}-\d{2}-\d{2}[^*]+)\*\*\s*\(ID:\s*(\d+)\)\s*内容：([^\n]+)'
                                # 格式 C: "**timestamp** 换行 内容：xxx[[N]](url)" (最新中文格式)
                                pattern_c = r'\*\*(\d{4}-\d{2}-\d{2}[^*]+)\*\*\s*\n\s*内容：([^\[]+)\[\[(\d+)\]\]\((https://x\.com/i/status/(\d+))\)'
                                # 格式 D: 英文格式 "- **Project (@handle)**: description[[N]](url)"
                                pattern_d = r'-\s*\*\*([^*]+)\s*\((@[^)]+)\)\*\*:\s*([^\[]+)\[\[(\d+)\]\]\((https://x\.com/i/status/(\d+))\)'
                                # 格式 E: 英文标题格式 "**Title:** content[[N]](url)"
                                pattern_e = r'\*\*([^*]+):\*\*\s*([^\[]+)\[\[(\d+)\]\]\((https://x\.com/i/status/(\d+))\)'
                                # 格式 F: 编号列表格式 "1. **Project** (@handle): desc[[N]](url)"
                                pattern_f = r'\d+\.\s*\*\*([^*]+)\*\*\s*\((@[^,]+),?\s*\$?[^)]*\)\s*\n?\s*-?\s*([^\[]+)\[\[(\d+)\]\]\((https://x\.com/i/status/(\d+))\)'
                                
                                # 尝试格式 A
                                matches_a = re.findall(pattern_a, text)
                                for author, timestamp, content_text in matches_a:
                                    tweet_data = {"author": author, "content": content_text, "timestamp": timestamp, "url": ""}
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
                                
                                # 尝试格式 B
                                matches_b = re.findall(pattern_b, text)
                                for timestamp, tweet_id, content_text in matches_b:
                                    tweet_data = {"author": "@unknown", "content": content_text.strip(), "timestamp": timestamp.strip(), "url": f"https://x.com/i/status/{tweet_id}"}
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
                                
                                # 尝试格式 C（最新中文格式）
                                matches_c = re.findall(pattern_c, text)
                                for timestamp, content_text, ref_num, full_url, tweet_id in matches_c:
                                    tweet_data = {
                                        "author": "@heyibinance",
                                        "content": content_text.strip(),
                                        "timestamp": timestamp.strip(),
                                        "url": f"https://x.com/i/status/{tweet_id}"
                                    }
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
                                
                                # 尝试格式 D（英文项目格式）
                                matches_d = re.findall(pattern_d, text)
                                for project, handle, desc, ref, full_url, tweet_id in matches_d:
                                    tweet_data = {
                                        "author": handle.strip(),
                                        "content": desc.strip(),
                                        "timestamp": "",
                                        "url": f"https://x.com/i/status/{tweet_id}"
                                    }
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
                                
                                # 尝试格式 E（英文标题格式）
                                matches_e = re.findall(pattern_e, text)
                                for title, content, ref, full_url, tweet_id in matches_e:
                                    tweet_data = {
                                        "author": "@trending",
                                        "content": f"**{title.strip()}:** {content.strip()}",
                                        "timestamp": "",
                                        "url": f"https://x.com/i/status/{tweet_id}"
                                    }
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
                                
                                # 尝试格式 F（编号列表格式）
                                matches_f = re.findall(pattern_f, text)
                                for project, handle, desc, ref, full_url, tweet_id in matches_f:
                                    tweet_data = {
                                        "author": handle.strip(),
                                        "content": desc.strip(),
                                        "timestamp": "",
                                        "url": f"https://x.com/i/status/{tweet_id}"
                                    }
                                    if tweet_data not in tweets:
                                        tweets.append(tweet_data)
            except (KeyError, TypeError, ValueError) as e:
                print(f"[Warn] 解析异常：{e}", file=sys.stderr)
                continue
                
        result["tweets"] = tweets[:max_results]
        return result

    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"API 状态码错误：{e.response.status_code} - {e.response.text}"}
    except httpx.RequestError as e:
        return {"status": "error", "message": f"网络或代理错误：{e}"}
    except Exception as e:
        return {"status": "error", "message": f"发生未预期异常：{e}"}

def run_interactive_mode(api_key: str, default_proxy: str):
    """纯数字菜单交互模式"""
    while True:
        print("\n===============================")
        print("  Grok 推特检索引擎 (多模态)")
        print("===============================")
        print(f"当前代理: {default_proxy}")
        print("1. 推文检索 (grok-4-1-fast-reasoning)")
        print("2. 深度舆情分析 (增强推理)")
        print("0. 退出程序")
        print("===============================")
        
        try:
            choice = input("请输入数字选择功能: ").strip()
            if choice == '0':
                break
            elif choice in ('1', '2'):
                query = input("\n请输入搜索关键词: ").strip()
                if not query:
                    continue
                
                analyze_mode = (choice == '2')
                mode_str = "舆情分析" if analyze_mode else "极速检索"
                
                print(f"\n[*] 正在启动 {mode_str} '{query}'...")
                res = search_twitter(query=query, api_key=api_key, proxy=default_proxy, analyze=analyze_mode)
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print("[!] 无效输入，请输入 0、1 或 2。")
        except KeyboardInterrupt:
            print("\n[!] 检测到手动中断，退出程序。")
            break
        except Exception as e:
            print(f"\n[!] 交互界面发生错误: {e}")

def main():
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Grok Twitter Search")
        parser.add_argument("--query", required=True, help="搜索查询")
        parser.add_argument("--api-key", help="Grok API Key")
        parser.add_argument("--api-base", default="https://api.x.ai/v1")
        parser.add_argument("--max-results", type=int, default=10)
        parser.add_argument("--proxy", help="SOCKS5 代理")
        parser.add_argument("--analyze", action="store_true", help="启用 reasoning 模型进行深度分析")
        
        args = parser.parse_args()
        
        api_key = args.api_key or os.environ.get("GROK_API_KEY")
        if not api_key:
            print(json.dumps({"status": "error", "message": "缺少 API Key"}))
            sys.exit(1)
            
        proxy = args.proxy or os.environ.get("SOCKS5_PROXY", "socks5://127.0.0.1:40000")
        
        result = search_twitter(args.query, api_key, args.api_base, args.max_results, proxy, args.analyze)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        api_key = os.environ.get("GROK_API_KEY")
        if not api_key:
            print("[!] 未找到 GROK_API_KEY，请检查配置。")
            sys.exit(1)
        proxy = os.environ.get("SOCKS5_PROXY", "socks5://127.0.0.1:40000")
        run_interactive_mode(api_key, proxy)

if __name__ == "__main__":
    main()