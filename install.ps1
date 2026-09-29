# ZCode-Jev 安装脚本
# 用法：
#   .\install.ps1                              仅显示安装步骤清单（不改任何东西）
#   .\install.ps1 -InstallSkills               把三个 skills 复制到 ~\.agents\skills（已存在则跳过）
#   .\install.ps1 -InstallSkills -Force        已存在的同名 skill 也覆盖
#
# 安全说明：本脚本只复制 skills，不会改动 ~/.zcode/cli/config.json 和 ~/.zcode/AGENTS.md
# （这两个文件请你按打印出的指引手动合并，避免脚本误伤你已有的配置）。
param(
    [switch]$InstallSkills,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$userSkills = Join-Path $env:USERPROFILE '.agents\skills'
$skillNames = @('grill-me', 'jev-test', 'jev-complete')

Write-Host ''
Write-Host '== ZCode-Jev 安装 ==' -ForegroundColor Cyan
Write-Host "工具包位置: $kitRoot"
Write-Host ''

# -- 第 1 步：安装 skills ----------------------------------------------------
if ($InstallSkills) {
    foreach ($name in $skillNames) {
        $src = Join-Path $kitRoot "skills\$name"
        $dst = Join-Path $userSkills $name
        if ((Test-Path $dst) -and -not $Force) {
            Write-Host "[跳过] $dst 已存在（避免覆盖你已有的同名 skill；确认要覆盖请加 -Force）" -ForegroundColor Yellow
        }
        else {
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force
            Write-Host "[已装] $dst" -ForegroundColor Green
        }
    }
}
else {
    Write-Host '第 1 步（未执行）安装 skills：' -ForegroundColor White
    Write-Host "  手动: 复制 $kitRoot\skills\ 下三个目录到 $userSkills\"
    Write-Host '  或运行: .\install.ps1 -InstallSkills'
}

# 无论是否执行复制，都要提示遮蔽风险（用户更常走安装分支）
Write-Host '  注意: 若 ~\.zcode\skills\ 里已有同名 skill，会遮蔽 ~\.agents\skills\ 的副本（扫描顺序更靠前）' -ForegroundColor DarkYellow

Write-Host ''

# -- 第 2 步：注册 MCP（手动） ------------------------------------------------
Write-Host '第 2 步（手动）注册 MCP server：' -ForegroundColor White
Write-Host '  把 mcp-config.example.json 里 servers.jev 一项合并进 ~/.zcode/cli/config.json 的 mcp.servers'
Write-Host '  并把 env.OPENROUTER_API_KEY 换成你的真实密钥（没有密钥也能装，工具会走离线回退）'
Write-Host '  也可以在 ZCode 的 Settings -> MCP 界面里添加 stdio server：'
Write-Host "    command: python    args: $kitRoot\jev_mcp.py"

Write-Host ''

# -- 第 3 步：全局规则（手动） --------------------------------------------------
Write-Host '第 3 步（手动）全局规则：' -ForegroundColor White
Write-Host '  把 AGENTS-jev.md 的内容并入 ~/.zcode/AGENTS.md（全局）或某仓库的 AGENTS.md（单仓库）'

Write-Host ''

# -- 验证 ---------------------------------------------------------------------
Write-Host '验证：' -ForegroundColor White
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    Write-Host "  python 已找到: $($python.Source)"
    Write-Host '  冒烟测试: cd 此目录后运行  python scripts\smoke_test.py   （应全部 PASS）'
}
else {
    Write-Host '  [注意] PATH 里没有 python；请改用 py 启动器并在 MCP 配置里相应调整' -ForegroundColor Yellow
}
Write-Host '  装好 MCP 后重启 ZCode，Settings -> MCP 里 jev 应显示已连接、5 个工具；'
Write-Host '  无密钥时调用任一工具应返回 {"jev": "offline", ...}，配好密钥后返回 {"jev": "ok", ...}'
Write-Host ''
