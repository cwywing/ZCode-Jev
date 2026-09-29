#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev_mcp.py 冒烟测试：不起 ZCode，直接用子进程对 server 说 MCP stdio JSON-RPC。

覆盖点：
  1. initialize 握手 + protocolVersion 回显
  2. ping
  3. tools/list 返回 5 个工具且 schema 合法
  4. 无密钥时 jev_route / jev_grill / jev_review / jev_risk / jev_complete 均返回 jev=offline 回退
  5. state 含疑似密钥（sk-/dk-/jv_live_）时拒绝（isError=true）
  6. 参数为空/非法时报参数错误（isError=true）
  7. 未知方法返回 -32601
  8. 网络失败与非 JSON 响应均走离线回退（isError=false）

用法：python scripts/smoke_test.py   （在 C:\\wwwroot\\ZCode-Jev 下运行）
"""

import json
import os
import subprocess
import sys
import threading

from http.server import BaseHTTPRequestHandler, HTTPServer

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


class McpClient(object):
    def __init__(self, extra_env=None):
        env = dict(os.environ)
        # 强制无密钥环境，保证走离线回退路径的确定性
        for var in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "DEFAPI_API_KEY", "JEV_ENDPOINT"):
            env.pop(var, None)
        env.update(extra_env or {})
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._id = 0

    def request(self, method, params=None):
        self._id += 1
        return self.send({"jsonrpc": "2.0", "id": self._id,
                          "method": method, "params": params or {}})

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}}, expect_reply=False)

    def send(self, message, expect_reply=True):
        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        if not expect_reply:
            return None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server 提前退出，stderr=%s" % self.proc.stderr.read().decode("utf-8", "replace"))
        return json.loads(line.decode("utf-8"))

    def call_tool(self, name, arguments):
        reply = self.request("tools/call", {"name": name, "arguments": arguments})
        result = reply.get("result") or {}
        text = ""
        for block in result.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")
        return result.get("isError", False), text

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main():
    client = McpClient()
    try:
        # 1. initialize 握手
        reply = client.request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0"},
        })
        info = (reply.get("result") or {}).get("serverInfo") or {}
        check("initialize 握手", info.get("name") == "jev" and "tools" in (reply["result"].get("capabilities") or {}))
        check("protocolVersion 回显", reply["result"].get("protocolVersion") == "2025-03-26",
              str(reply.get("result")))
        client.notify("notifications/initialized")

        # 2. ping
        reply = client.request("ping")
        check("ping", reply.get("result") == {})

        # 3. tools/list
        reply = client.request("tools/list")
        tools = (reply.get("result") or {}).get("tools") or []
        names = sorted(t.get("name") for t in tools)
        check("tools/list 返回 5 个工具",
              names == ["jev_complete", "jev_grill", "jev_review", "jev_risk", "jev_route"], str(names))
        schemas_ok = all(t.get("inputSchema", {}).get("type") == "object" for t in tools)
        check("工具 inputSchema 合法", schemas_ok)

        # 4. 离线回退
        is_error, text = client.call_tool("jev_route", {"state": "修复登录页按钮文字拼写错误"})
        payload = json.loads(text)
        check("jev_route 离线回退", not is_error and payload.get("jev") == "offline"
              and "fallback_advice" in payload, text[:200])

        is_error, text = client.call_tool("jev_grill", {
            "state": "为订单模块增加导出功能",
            "questions": json.dumps([
                {"question": "导出格式用 CSV 还是 Excel？", "recommendation": "CSV，零依赖"},
                "导出上限走配置还是写死？",
            ], ensure_ascii=False),
        })
        payload = json.loads(text)
        check("jev_grill 离线回退", not is_error and payload.get("jev") == "offline", text[:200])

        is_error, text = client.call_tool("jev_review", {
            "state": "订单导出功能验收",
            "checkpoints": json.dumps([
                {"checkpoint": "导出 CSV 首行是表头", "why": "验收标准"},
                "导出超过 1 万行时分批写出",
            ], ensure_ascii=False),
        })
        payload = json.loads(text)
        check("jev_review 离线回退", not is_error and payload.get("jev") == "offline", text[:200])

        is_error, text = client.call_tool("jev_risk", {"state": "生产库 TRUNCATE orders 表"})
        payload = json.loads(text)
        check("jev_risk 离线回退", not is_error and payload.get("jev") == "offline", text[:200])

        is_error, text = client.call_tool("jev_complete", {"state": "需求 A/B/C 均已实现，测试通过"})
        payload = json.loads(text)
        check("jev_complete 离线回退", not is_error and payload.get("jev") == "offline", text[:200])

        # 5. 密钥护栏
        is_error, text = client.call_tool("jev_route", {"state": "帮我把 sk-abcdef0123456789abcdef 换到配置里"})
        check("密钥护栏拒绝", is_error and "疑似包含密钥" in text, text[:200])

        is_error, text = client.call_tool("jev_route", {"state": "配置文件里有 dk-abcdef0123456789abcdef 别泄露"})
        check("defapi 密钥(dk-)护栏拒绝", is_error and "疑似包含密钥" in text, text[:200])

        is_error, text = client.call_tool("jev_route", {"state": "日志里出现了 jv_live_a1b2c3d4e5f6g7h8 要脱敏"})
        check("托管密钥(jv_live_)护栏拒绝", is_error and "疑似包含密钥" in text, text[:200])

        # 5b. 数组形式传参（MCP 客户端常直接传数组而非 JSON 文本）
        is_error, text = client.call_tool("jev_grill", {
            "state": "背景",
            "questions": ["问题一", {"question": "问题二", "recommendation": "推荐二"}],
        })
        payload = json.loads(text)
        check("questions 传数组可用", not is_error and payload.get("jev") == "offline", text[:200])

        is_error, text = client.call_tool("jev_review", {
            "state": "背景",
            "checkpoints": [{"checkpoint": "检查点一", "why": "验收"}],
        })
        payload = json.loads(text)
        check("checkpoints 传数组可用", not is_error and payload.get("jev") == "offline", text[:200])

        # 5c. 网络失败 → 离线回退（而非 isError），契约与文档一致
        net_client = McpClient({
            "JEV_ENDPOINT": "http://127.0.0.1:1/",  # 本地关闭端口，连接必然被拒
            "OPENROUTER_API_KEY": "sk-or-v1-fake0123456789abcdef",
        })
        try:
            is_error, text = net_client.call_tool("jev_route", {"state": "网络故障模拟"})
            payload = json.loads(text)
            check("网络失败→离线回退(非报错)",
                  not is_error and payload.get("jev") == "offline" and "网络" in payload.get("reason", ""),
                  text[:250])
        finally:
            net_client.close()

        # 5d. 200 但 body 不是 JSON（网关错误页）→ 离线回退
        class _FakeGateway(BaseHTTPRequestHandler):
            def do_POST(self):
                body = b"<html>502 gateway error page</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        gateway = HTTPServer(("127.0.0.1", 0), _FakeGateway)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        gateway_client = McpClient({
            "JEV_ENDPOINT": "http://127.0.0.1:%d/" % gateway.server_port,
            "OPENROUTER_API_KEY": "sk-or-v1-fake0123456789abcdef",
        })
        try:
            is_error, text = gateway_client.call_tool("jev_route", {"state": "非JSON响应模拟"})
            payload = json.loads(text)
            check("非JSON响应→离线回退(非报错)",
                  not is_error and payload.get("jev") == "offline" and "JSON" in payload.get("reason", ""),
                  text[:250])
        finally:
            gateway_client.close()
            gateway.shutdown()

        # 6. 空参数
        is_error, text = client.call_tool("jev_route", {"state": "  "})
        check("空 state 报参数错误", is_error and "state" in text, text[:200])

        is_error, text = client.call_tool("jev_grill", {"state": "背景", "questions": "不是JSON"})
        check("非法 questions 报参数错误", is_error, text[:200])

        # 7. 未知方法
        reply = client.request("resources/list")
        check("未知方法 -32601", (reply.get("error") or {}).get("code") == -32601, str(reply))
    finally:
        client.close()

    print("")
    print("结果：%d 通过 / %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
