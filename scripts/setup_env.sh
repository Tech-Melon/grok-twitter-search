#!/bin/bash
# Grok Twitter Search - 环境初始化脚本
# 自动检测并配置 WARP 代理

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🍉 Grok Twitter Search - 环境初始化"
echo "===================================="

# 颜色定义
GREEN='\e[0;32m'
YELLOW='\e[1;33m'
RED='\e[0;31m'
NC='\e[0m' # No Color

# 检测 WARP 是否可用
detect_warp() {
    # 检查 WARP 进程
    if ! pgrep -x "warp-svc" > /dev/null 2>&1; then
        return 1
    fi
    
    # 检查 SOCKS5 端口 (40000 是 WARP 默认端口)
    if command -v netstat > /dev/null 2>&1; then
        if netstat -tuln 2>/dev/null | grep -q ":40000"; then
            return 0
        fi
    elif command -v ss > /dev/null 2>&1; then
        if ss -tuln 2>/dev/null | grep -q ":40000"; then
            return 0
        fi
    fi
    
    return 1
}

# 测试代理连通性
test_proxy() {
    local proxy_url=$1
    local test_url="https://api.x.ai/v1"
    
    if [ -z "$proxy_url" ]; then
        # 直连测试
        if curl -s --connect-timeout 5 "$test_url" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200\|401\|403"; then
            return 0
        fi
    else
        # 代理测试
        local proxy_host=$(echo "$proxy_url" | sed -E 's/socks5:\/\/([^:]+):.*/\1/')
        local proxy_port=$(echo "$proxy_url" | sed -E 's/socks5:\/\/[^:]+:(.*)/\1/')
        
        if curl -s --socks5 "$proxy_host:$proxy_port" --connect-timeout 5 "$test_url" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200\|401\|403"; then
            return 0
        fi
    fi
    
    return 1
}

# 主逻辑
main() {
    # 优先级1: 用户已设置 SOCKS5_PROXY
    if [ -n "$SOCKS5_PROXY" ]; then
        echo -e "${GREEN}✅ 使用用户配置的代理: $SOCKS5_PROXY${NC}"
        if test_proxy "$SOCKS5_PROXY"; then
            echo -e "${GREEN}✅ 代理连接测试通过${NC}"
            export SOCKS5_PROXY
            exit 0
        else
            echo -e "${YELLOW}⚠️  配置的代理无法连通，尝试其他方式...${NC}"
        fi
    fi
    
    # 优先级2: 自动检测 WARP
    if detect_warp; then
        echo -e "${GREEN}✅ 检测到 WARP 运行中${NC}"
        TEMP_PROXY="socks5://127.0.0.1:40000"
        
        if test_proxy "$TEMP_PROXY"; then
            echo -e "${GREEN}✅ WARP 代理测试通过，自动启用${NC}"
            export SOCKS5_PROXY="$TEMP_PROXY"
            echo "export SOCKS5_PROXY=\"$TEMP_PROXY\""
            exit 0
        else
            echo -e "${YELLOW}⚠️  WARP 进程存在但代理端口不通${NC}"
        fi
    fi
    
    # 优先级3: 尝试直连
    echo -e "${YELLOW}ℹ️  未检测到代理配置，测试直连...${NC}"
    
    if test_proxy ""; then
        echo -e "${GREEN}✅ 直连可用，无需代理${NC}"
        export SOCKS5_PROXY=""
        exit 0
    fi
    
    # 所有方式都失败
    echo -e "${RED}❌ 无法连接到 Grok API${NC}"
    echo ""
    echo "可能的解决方案："
    echo "1. 安装并启动 WARP:"
    echo "   curl -fsSL https://pkg.cloudflareclient.com/cloudflare-warp.asc | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg"
    echo "   echo 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main' | sudo tee /etc/apt/sources.list.d/cloudflare-client.list"
    echo "   sudo apt update && sudo apt install cloudflare-warp"
    echo "   sudo systemctl start warp-svc"
    echo ""
    echo "2. 手动设置代理环境变量:"
    echo "   export SOCKS5_PROXY=socks5://your-proxy:port"
    echo ""
    echo "3. 检查网络连接和防火墙设置"
    echo ""
    
    exit 1
}

main "$@"
