#!/usr/bin/env python3
"""
Grok Twitter Search - 交互式配置向导
帮助用户快速完成环境配置
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path

def print_header():
    print("\n" + "="*50)
    print("  🍉 Grok Twitter Search - 交互式配置向导")
    print("="*50 + "\n")

def print_step(step_num, total, title):
    print(f"\n📌 步骤 {step_num}/{total}: {title}")
    print("-" * 40)

def check_uv():
    """检查 uv 是否安装"""
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ uv 已安装: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ uv 未安装")
    print("   uv 是 Python 包管理器，用于隔离依赖环境")
    print("   安装命令: curl -LsSf https://astral.sh/uv/install.sh | sh")
    return False

def check_curl():
    """检查 curl 是否安装"""
    try:
        result = subprocess.run(["curl", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"✅ curl 已安装: {version[:50]}...")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ curl 未安装")
    print("   请使用系统包管理器安装 curl")
    return False

def check_warp():
    """检查 WARP 状态"""
    # 检查进程
    try:
        result = subprocess.run(["pgrep", "-x", "warp-svc"], capture_output=True)
        warp_running = result.returncode == 0
    except:
        warp_running = False
    
    # 检查端口
    port_listening = False
    try:
        result = subprocess.run(["ss", "-tuln"], capture_output=True, text=True)
        if ":40000" in result.stdout:
            port_listening = True
    except:
        try:
            result = subprocess.run(["netstat", "-tuln"], capture_output=True, text=True)
            if ":40000" in result.stdout:
                port_listening = True
        except:
            pass
    
    if warp_running and port_listening:
        print("✅ WARP 服务运行中，端口 40000 监听正常")
        return True, True
    elif warp_running:
        print("⚠️  WARP 进程存在，但端口 40000 未监听")
        print("   可能需要连接 WARP: warp-cli connect")
        return True, False
    else:
        print("❌ WARP 未安装或未运行")
        return False, False

def setup_grok_api_key():
    """配置 Grok API Key"""
    current_key = os.environ.get("GROK_API_KEY", "")
    
    if current_key:
        masked = f"{current_key[:8]}******{current_key[-6:]}"
        print(f"当前 GROK_API_KEY: {masked}")
        choice = input("是否更换? [y/N]: ").strip().lower()
        if choice != 'y':
            return current_key
    
    print("\n💡 获取 API Key:")
    print("   1. 访问 https://x.ai/api")
    print("   2. 注册/登录账号")
    print("   3. 创建 API Key")
    print("   免费额度: $25/月\n")
    
    while True:
        api_key = input("请输入你的 Grok API Key: ").strip()
        
        if not api_key:
            print("❌ API Key 不能为空")
            continue
        
        if not api_key.startswith("xai-"):
            print("⚠️  API Key 格式不正确，应以 'xai-' 开头")
            confirm = input("是否继续? [y/N]: ").strip().lower()
            if confirm != 'y':
                continue
        
        # 简单验证长度
        if len(api_key) < 20:
            print("❌ API Key 长度过短，请检查输入")
            continue
        
        print("✅ API Key 已接收")
        return api_key

def setup_proxy(warp_available):
    """配置代理"""
    current_proxy = os.environ.get("SOCKS5_PROXY", "")
    
    print("\n🌐 代理配置选项:")
    print("   1. 自动检测 (推荐)")
    print("   2. 使用 WARP 代理 (socks5://127.0.0.1:40000)")
    print("   3. 自定义 SOCKS5 代理")
    print("   4. 不使用代理 (直连)")
    
    if current_proxy:
        print(f"\n   当前配置: {current_proxy}")
    
    choice = input("\n请选择 [1-4] (默认: 1): ").strip() or "1"
    
    if choice == "1":
        print("✅ 将使用自动检测模式")
        return "auto"
    
    elif choice == "2":
        if not warp_available:
            print("⚠️  WARP 似乎未运行，确定要使用此配置吗?")
            confirm = input("   [y/N]: ").strip().lower()
            if confirm != 'y':
                return setup_proxy(warp_available)
        print("✅ 将使用 WARP 代理: socks5://127.0.0.1:40000")
        return "socks5://127.0.0.1:40000"
    
    elif choice == "3":
        proxy = input("请输入 SOCKS5 代理地址 (如 socks5://host:port): ").strip()
        if not proxy.startswith("socks5://"):
            print("⚠️  地址应以 'socks5://' 开头")
            confirm = input("是否继续? [y/N]: ").strip().lower()
            if confirm != 'y':
                return setup_proxy(warp_available)
        print(f"✅ 将使用自定义代理: {proxy}")
        return proxy
    
    elif choice == "4":
        print("✅ 将使用直连模式")
        return ""
    
    else:
        print("❌ 无效选择，使用自动检测")
        return "auto"

def test_connection(api_key, proxy):
    """测试连接"""
    print("\n🧪 测试连接到 Grok API...")
    
    script_dir = Path(__file__).parent
    search_script = script_dir / "search_twitter.py"
    
    cmd = [
        "uv", "run", str(search_script),
        "--query", "test",
        "--max-results", "1",
        "--api-key", api_key
    ]
    
    if proxy and proxy != "auto":
        env = os.environ.copy()
        env["SOCKS5_PROXY"] = proxy
    else:
        env = os.environ.copy()
        # 如果 proxy 是 auto，让脚本自己检测
        if "SOCKS5_PROXY" in env:
            del env["SOCKS5_PROXY"]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data.get("status") == "success":
                    print("✅ 连接测试成功!")
                    print(f"   获取到 {len(data.get('tweets', []))} 条推文")
                    return True
                else:
                    print(f"❌ API 返回错误: {data.get('message', '未知错误')}")
                    return False
            except json.JSONDecodeError:
                print("❌ 无法解析响应")
                print(f"   输出: {result.stdout[:200]}")
                return False
        else:
            print(f"❌ 测试失败")
            print(f"   错误: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ 连接超时")
        return False
    except Exception as e:
        print(f"❌ 测试出错: {e}")
        return False

def save_config(api_key, proxy_choice):
    """保存配置建议"""
    print("\n💾 配置保存建议")
    print("=" * 50)
    
    # 方法1: Shell 配置文件
    shell_rc = "~/.bashrc"
    if "zsh" in os.environ.get("SHELL", ""):
        shell_rc = "~/.zshrc"
    
    print(f"\n方法 1: 添加到 {shell_rc}")
    print("-" * 40)
    print(f'export GROK_API_KEY="{api_key}"')
    if proxy_choice and proxy_choice != "auto":
        print(f'export SOCKS5_PROXY="{proxy_choice}"')
    
    # 方法2: OpenClaw 配置
    print(f"\n方法 2: 添加到 ~/.openclaw/openclaw.json")
    print("-" * 40)
    config = {
        "skills": {
            "entries": {
                "grok-twitter-search": {
                    "enabled": True,
                    "env": {
                        "GROK_API_KEY": api_key
                    }
                }
            }
        }
    }
    if proxy_choice and proxy_choice != "auto":
        config["skills"]["entries"]["grok-twitter-search"]["env"]["SOCKS5_PROXY"] = proxy_choice
    
    print(json.dumps(config, indent=2))
    
    # 询问是否写入 openclaw.json
    print("\n是否自动写入 ~/.openclaw/openclaw.json?")
    choice = input("[y/N]: ").strip().lower()
    
    if choice == 'y':
        try:
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 读取现有配置
            existing = {}
            if config_path.exists():
                with open(config_path, 'r') as f:
                    content = f.read()
                    # 处理 JSON5 注释
                    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
                    try:
                        existing = json.loads(content)
                    except:
                        existing = {}
            
            # 合并配置
            if "skills" not in existing:
                existing["skills"] = {}
            if "entries" not in existing["skills"]:
                existing["skills"]["entries"] = {}
            
            existing["skills"]["entries"]["grok-twitter-search"] = config["skills"]["entries"]["grok-twitter-search"]
            
            # 写回 (使用 JSON5 格式保留注释友好性)
            with open(config_path, 'w') as f:
                json.dump(existing, f, indent=2)
            
            print(f"✅ 配置已写入: {config_path}")
            print("   重启 OpenClaw Gateway 后生效")
            
        except Exception as e:
            print(f"❌ 写入失败: {e}")
            print("   请手动复制上面的配置")

def main():
    print_header()
    
    # 步骤 1: 检查依赖
    print_step(1, 4, "检查系统依赖")
    uv_ok = check_uv()
    curl_ok = check_curl()
    
    if not uv_ok:
        print("\n⚠️  缺少 uv，部分功能可能受限")
        print("   但 skill 仍可通过其他方式运行")
    
    # 步骤 2: 检查 WARP
    print_step(2, 4, "检查 WARP 代理")
    warp_installed, warp_ready = check_warp()
    
    if not warp_installed:
        print("\n💡 WARP 安装指南:")
        print("   Ubuntu/Debian:")
        print("   curl -fsSL https://pkg.cloudflareclient.com/cloudflare-warp.asc | \\")
        print("     sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg")
        print("   echo 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] \\")
        print("     https://pkg.cloudflareclient.com/ $(lsb_release -cs) main' | \\")
        print("     sudo tee /etc/apt/sources.list.d/cloudflare-client.list")
        print("   sudo apt update && sudo apt install cloudflare-warp")
        print("   sudo systemctl start warp-svc")
        print("   warp-cli registration new && warp-cli connect")
    
    # 步骤 3: 配置 API Key 和代理
    print_step(3, 4, "配置 API Key 和代理")
    api_key = setup_grok_api_key()
    proxy_choice = setup_proxy(warp_ready)
    
    # 步骤 4: 测试连接
    print_step(4, 4, "测试连接")
    success = test_connection(api_key, proxy_choice)
    
    if success:
        print("\n🎉 配置成功!")
        save_config(api_key, proxy_choice)
    else:
        print("\n⚠️  连接测试失败，但仍保存配置?")
        choice = input("是否继续保存? [y/N]: ").strip().lower()
        if choice == 'y':
            save_config(api_key, proxy_choice)
    
    print("\n" + "="*50)
    print("  配置完成! 使用方法:")
    print("="*50)
    print("\n  在 OpenClaw 中直接说:")
    print('  "搜索推特上关于 Bitcoin 的最新讨论"')
    print("\n  或手动运行:")
    print("  uv run scripts/search_twitter.py --query \"Bitcoin\" --max-results 10")
    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 已取消配置")
        sys.exit(0)
