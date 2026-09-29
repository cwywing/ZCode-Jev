#!/usr/bin/env bash
# ZCode-Jev 安装脚本（macOS / Linux）
# 用法：
#   ./install.sh                 仅显示安装步骤清单（不改任何东西）
#   ./install.sh --install-skills 把三个 skills 复制到 ~/.agents/skills（已存在则跳过）
#   ./install.sh --install-skills --force  已存在的同名 skill 也覆盖
#
# 安全说明：本脚本只复制 skills，不会改动 ~/.zcode/cli/config.json 和 ~/.zcode/AGENTS.md
# （这两个文件请按打印出的指引手动合并，避免脚本误伤你已有的配置）。

set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SKILLS="$HOME/.agents/skills"
SKILL_NAMES=(grill-me jev-test jev-complete)

INSTALL_SKILLS=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --install-skills) INSTALL_SKILLS=1 ;;
    --force) FORCE=1 ;;
    *) echo "未知参数：$arg（可用：--install-skills --force）"; exit 1 ;;
  esac
done

echo ""
echo "== ZCode-Jev 安装 =="
echo "工具包位置: $KIT_ROOT"
echo ""

# -- 第 1 步：安装 skills ------------------------------------------------------
if [ "$INSTALL_SKILLS" -eq 1 ]; then
  for name in "${SKILL_NAMES[@]}"; do
    src="$KIT_ROOT/skills/$name"
    dst="$USER_SKILLS/$name"
    if [ -d "$dst" ] && [ "$FORCE" -eq 0 ]; then
      echo "[跳过] $dst 已存在（避免覆盖你已有的同名 skill；确认要覆盖请加 --force）"
    else
      mkdir -p "$dst"
      cp -R "$src/." "$dst/"
      echo "[已装] $dst"
    fi
  done
else
  echo "第 1 步（未执行）安装 skills："
  echo "  手动: 复制 $KIT_ROOT/skills/ 下三个目录到 $USER_SKILLS/"
  echo "  或运行: ./install.sh --install-skills"
fi

# 无论是否执行复制，都要提示遮蔽风险（用户更常走安装分支）
echo "  注意: 若 ~/.zcode/skills/ 里已有同名 skill，会遮蔽 ~/.agents/skills/ 的副本（扫描顺序更靠前）"

echo ""

# -- 第 2 步：注册 MCP（手动） ---------------------------------------------------
echo "第 2 步（手动）注册 MCP server："
echo "  把 mcp-config.example.json 里 servers.jev 一项合并进 ~/.zcode/cli/config.json 的 mcp.servers"
echo "  并把 env.OPENROUTER_API_KEY 换成你的真实密钥（没有密钥也能装，工具会走离线回退）"
echo "  macOS 注意：command 用 python3，args 里的路径换成实际路径，例如："
echo "    \"command\": \"python3\", \"args\": [\"$KIT_ROOT/jev_mcp.py\"]"
echo "  也可以在 ZCode 的 Settings -> MCP 界面里添加 stdio server。"

echo ""

# -- 第 3 步：全局规则（手动） -----------------------------------------------------
echo "第 3 步（手动）全局规则："
echo "  把 AGENTS-jev.md 的内容并入 ~/.zcode/AGENTS.md（全局）或某仓库的 AGENTS.md（单仓库）"

echo ""

# -- 验证 -----------------------------------------------------------------------
echo "验证："
if command -v python3 >/dev/null 2>&1; then
  echo "  python3 已找到: $(command -v python3)"
  echo "  冒烟测试: cd 此目录后运行  python3 scripts/smoke_test.py   （应全部 PASS）"
elif command -v python >/dev/null 2>&1; then
  echo "  python 已找到: $(command -v python)"
  echo "  冒烟测试: cd 此目录后运行  python scripts/smoke_test.py   （应全部 PASS）"
else
  echo "  [注意] 未找到 python3/python；请先安装 Python 3.7+ 再使用本工具包"
fi
echo "  装好 MCP 后重启 ZCode，Settings -> MCP 里 jev 应显示已连接、5 个工具；"
echo "  无密钥时调用任一工具应返回 {\"jev\": \"offline\", ...}，配好密钥后返回 {\"jev\": \"ok\", ...}"
echo ""
