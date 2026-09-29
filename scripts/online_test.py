#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在线端到端自测：起一个带真实密钥的 jev_mcp 子进程，把 5 个工具全部真实调用一遍。

密钥查找顺序（支持两种 provider）：
  1. 环境变量 OPENROUTER_API_KEY / TYPESAFE_API_KEY
  2. ~/.zcode/cli/config.json → mcp.servers.jev.env 里的 OPENROUTER_API_KEY / TYPESAFE_API_KEY
     （自动识别占位符；找到哪个就按哪个 provider 调用，不会张冠李戴）

用法：
  python scripts/online_test.py

- 未配置密钥：只重放离线回退验证（应全部 offline），并打印填 key 指引，退出码 0。
- 已配置密钥：5 个工具应全部返回 jev=ok，并打印真实决策结果。
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "jev_mcp.py")

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("[PASS] %s" % name)
    else:
        FAIL += 1
        print("[FAIL] %s  %s" % (name, detail))


def find_api_key():
    """返回 (env_var_name, key, 来源说明)；找不到或仍是占位符时返回 (None, None, 原因)。"""
    for var in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "DEFAPI_API_KEY"):
        value = os.getenv(var, "").strip()
        if value:
            return var, value, "环境变量 %s" % var
    path = os.path.join(os.path.expanduser("~"), ".zcode", "cli", "config.json")
    try:
        with open(path, encoding="utf-8") as handle:
            servers = ((json.load(handle).get("mcp") or {}).get("servers") or {})
            env = (servers.get("jev") or {}).get("env") or {}
    except Exception:
        return None, None, "读不到 %s" % path
    for var in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "DEFAPI_API_KEY"):
        value = str(env.get(var, "")).strip()
        if value:
            if "替换" in value or "粘贴" in value or "你的" in value or len(value) < 20:
                return None, None, "config.json 里 mcp.servers.jev.env.%s 还是占位符/过短" % var
            return var, value, "config.json → mcp.servers.jev.env.%s" % var
    return None, None, "config.json 的 jev.env 里没有 OPENROUTER_API_KEY / TYPESAFE_API_KEY / DEFAPI_API_KEY"


class Client(object):
    def __init__(self, env):
        full_env = dict(os.environ)
        for var in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "DEFAPI_API_KEY"):
            full_env.pop(var, None)
        full_env.update(env)
        full_env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", SERVER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=full_env,
        )
        self._id = 0

    def request(self, method, params=None):
        self._id += 1
        self.proc.stdin.write((json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server 提前退出：%s" % self.proc.stderr.read().decode("utf-8", "replace"))
        return json.loads(line.decode("utf-8"))

    def call_tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments}).get("result") or {}
        text = "".join(b.get("text", "") for b in result.get("content") or [] if b.get("type") == "text")
        return result.get("isError", False), text

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def preflight_typesafe(key):
    """TypeSafe 密钥轻量预检：GET /v1/models。

    200 = 密钥有效；401 = 密钥本身无效（复制截断 / 已吊销 / 不是 TypeSafe 的 key）。
    参见 https://jevaiguide.com/errors/401-unauthorized/ 的判定法。
    """
    request = urllib.request.Request(
        "https://api.typesafe.ai/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return exc.code, body
    except Exception as exc:
        return None, str(exc)[:200]


def main():
    env_var, key, source = find_api_key()
    provider = {"OPENROUTER_API_KEY": "openrouter", "TYPESAFE_API_KEY": "typesafe",
                "DEFAPI_API_KEY": "defapi"}.get(env_var)
    print("密钥来源：%s\n" % (source if key else "%s（离线模式）" % source))
    if key and provider == "typesafe":
        code, body = preflight_typesafe(key)
        if code == 200:
            print("[预检] /v1/models → HTTP 200，密钥有效，开始 5 工具在线测试\n")
        elif code == 401:
            print("[预检] /v1/models → HTTP 401：密钥本身无效（复制截断 / 已吊销 / 不是 TypeSafe 的 key）")
            print("       处理：到 https://console.typesafe.ai/keys 新建 key，")
            print("       完整替换 config.json 里 jev.env.TYPESAFE_API_KEY 的值后重跑本脚本\n")
            sys.exit(2)
        else:
            print("[预检] /v1/models → HTTP %s：%s（无法判定，继续完整测试）\n" % (code, body))
    client = Client({env_var: key} if key else {})
    try:
        cases = [
            ("jev_route", {"state": "修复用户反馈页在 375px 宽度下按钮溢出的布局问题，涉及单个 CSS 文件"}, "level"),
            ("jev_grill", {"state": "为订单模块新增导出功能",
                           "questions": json.dumps([
                               {"question": "导出格式用 CSV 还是 Excel？", "recommendation": "CSV，零依赖"},
                               "并发导出超过多少行需要分批？",
                               "导出接口要不要鉴权？",
                           ], ensure_ascii=False)}, "results"),
            ("jev_review", {"state": "订单导出功能验收：格式正确、大数据量不超时、越权访问被拒绝",
                            "checkpoints": json.dumps([
                                {"checkpoint": "导出文件首行为表头且编码为 UTF-8 BOM", "why": "Excel 打开不乱码"},
                                {"checkpoint": "无权限用户调用导出接口返回 403", "why": "安全边界"},
                                {"checkpoint": "50 万行导出不超时且分批写出", "why": "验收标准"},
                            ], ensure_ascii=False)}, "results"),
            ("jev_risk", {"state": "在生产库执行 TRUNCATE orders 之前先做全表备份，然后清空并重建索引"}, "dangerous"),
            ("jev_complete", {"state": "需求：修复 375px 布局溢出。修改：1 个 CSS 文件 3 处规则。"
                                       "测试：Chrome 375px 真机宽度手动验证 + smoke 截图。遗留：无"}, "completed"),
        ]
        for tool, args, field in cases:
            is_error, text = client.call_tool(tool, args)
            try:
                payload = json.loads(text)
            except ValueError:
                check(tool, False, "返回不是 JSON：%s" % text[:200])
                continue
            if key:
                check("%s 在线返回 ok" % tool,
                      not is_error and payload.get("jev") == "ok" and field in payload,
                      text[:300])
                print("      ↳ %s" % json.dumps(payload, ensure_ascii=False)[:220])
            else:
                check("%s 离线回退" % tool,
                      not is_error and payload.get("jev") == "offline" and "fallback_advice" in payload,
                      text[:300])
    finally:
        client.close()

    print("")
    if key:
        print("结果：%d 通过 / %d 失败（在线模式，provider=%s，真实 API）" % (PASS, FAIL, provider))
    else:
        print("结果：%d 通过 / %d 失败（离线模式）" % (PASS, FAIL))
        print("")
        print("填入密钥后重跑本脚本即可做真实在线验证（两个 provider 任选其一）：")
        print("  A. OpenRouter：https://openrouter.ai/settings/keys 创建 key")
        print("  B. Jev 官方 TypeSafe：https://docs.typesafe.ai 注册获取 key")
        print("  然后编辑 C:\\Users\\%s\\.zcode\\cli\\config.json 的 jev.env，" % os.getenv("USERNAME", "你"))
        print("  填 OPENROUTER_API_KEY 或 TYPESAFE_API_KEY（二选一，自动识别 provider）")
        print("  （或先临时测试：set OPENROUTER_API_KEY=sk-or-... 再跑本脚本）")
        print("  最后：python scripts/online_test.py")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
