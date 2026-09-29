#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jev MCP server — ZCode 版轻量决策外脑。

零依赖：只用 Python 标准库（3.7+），以 MCP stdio（换行分隔的 JSON-RPC 2.0）对外提供服务，
注册后工具名为 mcp__jev__jev_route / jev_grill / jev_risk / jev_complete。

四个决策门工具：
  jev_route     开工前复杂度分级       quick / medium / high / xhigh
  jev_grill     规划期候选问题批量过滤  ask_user / inspect_code / infer_safely / unnecessary / duplicate
  jev_review    测试期检查点批量评审     重要性 / 是否留证 / 最佳证据类型
  jev_risk      危险操作风险判断        dangerous: true / false（附概率）
  jev_complete  收工前完成度判断        completed + thoroughness 四档

环境变量：
  OPENROUTER_API_KEY  OpenRouter 密钥（走 https://openrouter.ai/api/alpha/decisions，
                      模型默认 ~typesafe/jev-latest）
  TYPESAFE_API_KEY    Jev 官方（TypeSafe）密钥（走 https://api.typesafe.ai/v1/systemone，
                      模型默认 jev-latest）
  DEFAPI_API_KEY      defapi.org 中转站密钥（dk- 开头，走 https://api.defapi.org/api/v1/decisions，
                      模型默认 typesafe/jev-1.13，报文与 TypeSafe 官方格式一致）
  JEV_PROVIDER        可选，显式指定 "openrouter" / "typesafe" / "defapi"；不设时自动：
                      按已配置的密钥选择（OPENROUTER → TYPESAFE → DEFAPI 顺序）
  JEV_MODEL           可选，覆盖默认模型
  JEV_ENDPOINT        可选，强制覆盖端点 URL（调试用）
  JEV_TIMEOUT         可选，HTTP 超时秒数，默认 30

行为约定：
  - state / questions 里疑似出现密钥、Token、私钥时直接拒绝（isError），要求改发摘要。
  - 无密钥、网络失败、限流、超时 → 不抛错，返回 {"jev": "offline", "reason": ..., "fallback_advice": ...}，
    由调用方自行决策并在结果中注明 "Jev 离线，自行判定"。
  - 密钥认证失败（401/403）作为 isError 返回，避免配置错误被静默降级掩盖。
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SERVER_NAME = "jev"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION_DEFAULT = "2024-11-05"

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_DEFAULT_MODEL = "~typesafe/jev-latest"
TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_DEFAULT_MODEL = "jev-latest"
DEFAPI_ENDPOINT = "https://api.defapi.org/api/v1/decisions"
DEFAPI_DEFAULT_MODEL = "typesafe/jev-1.13"

GRILL_MAX_ITEMS = 20


class ToolInputError(Exception):
    """调用参数不合法，返回 isError 让调用方修正后重试。"""


class JevRefused(Exception):
    """输入疑似包含密钥，拒绝发送。"""


class JevAuthError(Exception):
    """API 密钥认证失败，属于配置错误，需要显式暴露。"""


# 疑似密钥特征：命中即拒绝调用（宁误报不漏报，误报时改写摘要即可）
_SECRET_MARKERS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk_or_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"dk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"jv_live_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|access[_-]?token|auth[_-]?token|password)"
               r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{12,}"),
]

_SECRET_HINT = ("输入中疑似包含密钥/Token/私钥，已拒绝发送给 Jev。"
                "请删除敏感值后改发精简摘要（例如用 <DB密码已省略> 代替），再重试。")


def _log(msg):
    sys.stderr.write("[jev] %s\n" % msg)
    sys.stderr.flush()


def _assert_no_secrets(*texts):
    for text in texts:
        if not text:
            continue
        for pattern in _SECRET_MARKERS:
            if pattern.search(text):
                raise JevRefused(_SECRET_HINT)


# ---------------------------------------------------------------------------
# 端点与密钥解析
# ---------------------------------------------------------------------------

def _resolve_backend():
    """返回 (endpoint, api_key, model, provider, 不可用原因)；密钥可用时原因为 None。

    provider 优先级：JEV_ENDPOINT 强制覆盖 > JEV_PROVIDER 显式指定 > 按已有密钥自动选择
    （OPENROUTER_API_KEY → TYPESAFE_API_KEY → DEFAPI_API_KEY）。
    显式锁定某 provider 但缺对应密钥时，不借用另一家的密钥（避免张冠李戴），
    而是带明确原因走离线回退。
    """
    endpoint = os.getenv("JEV_ENDPOINT")
    model = os.getenv("JEV_MODEL")
    provider = (os.getenv("JEV_PROVIDER") or "").strip().lower()
    _none = "OPENROUTER_API_KEY / TYPESAFE_API_KEY / DEFAPI_API_KEY 均未设置"

    if endpoint:
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("TYPESAFE_API_KEY") or os.getenv("DEFAPI_API_KEY")
        reason = None if api_key else "JEV_ENDPOINT 已设置，但 OPENROUTER_API_KEY / TYPESAFE_API_KEY / DEFAPI_API_KEY 均未配置"
        return endpoint, api_key, model or OPENROUTER_DEFAULT_MODEL, "custom", reason
    if provider == "typesafe":
        api_key = os.getenv("TYPESAFE_API_KEY")
        reason = None if api_key else "JEV_PROVIDER=typesafe，但未配置 TYPESAFE_API_KEY（不会借用其他家的密钥）"
        return TYPESAFE_ENDPOINT, api_key, model or TYPESAFE_DEFAULT_MODEL, "typesafe", reason
    if provider == "defapi":
        api_key = os.getenv("DEFAPI_API_KEY")
        reason = None if api_key else "JEV_PROVIDER=defapi，但未配置 DEFAPI_API_KEY（不会借用其他家的密钥）"
        return DEFAPI_ENDPOINT, api_key, model or DEFAPI_DEFAULT_MODEL, "defapi", reason
    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        reason = None if api_key else "JEV_PROVIDER=openrouter，但未配置 OPENROUTER_API_KEY（不会借用其他家的密钥）"
        return OPENROUTER_ENDPOINT, api_key, model or OPENROUTER_DEFAULT_MODEL, "openrouter", reason
    if os.getenv("OPENROUTER_API_KEY"):
        return OPENROUTER_ENDPOINT, os.getenv("OPENROUTER_API_KEY"), model or OPENROUTER_DEFAULT_MODEL, "openrouter", None
    if os.getenv("TYPESAFE_API_KEY"):
        return TYPESAFE_ENDPOINT, os.getenv("TYPESAFE_API_KEY"), model or TYPESAFE_DEFAULT_MODEL, "typesafe", None
    if os.getenv("DEFAPI_API_KEY"):
        return DEFAPI_ENDPOINT, os.getenv("DEFAPI_API_KEY"), model or DEFAPI_DEFAULT_MODEL, "defapi", None
    return None, None, None, "none", _none


def _timeout():
    try:
        return max(5, int(os.getenv("JEV_TIMEOUT", "30")))
    except ValueError:
        return 30


def _post_decisions(endpoint, api_key, model, state, questions):
    """调用 decisions 端点，返回解析后的 dict。网络/限流/超时/响应非 JSON 抛 JevUnavailable。

    state 直接作为请求的 state 字段发送：字符串包装成 {"task": state}，
    dict 原样发送——jev_grill/jev_review 用它附带整批候选清单，
    否则每道题只看得见自己，模型无法判断 duplicate。
    """
    if not isinstance(state, dict):
        state = {"task": state}
    payload = json.dumps({
        "model": model,
        "state": state,
        "questions": questions,
    }).encode("utf-8")

    def _once():
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_timeout()) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if exc.code in (401, 403):
                raise JevAuthError("Jev 端点认证失败（HTTP %d）：%s" % (exc.code, body))
            if exc.code in (429, 529):
                # 限流/过载：文档建议退避重试
                raise _RetryableHTTP(exc.code, body)
            if exc.code == 422:
                raise ToolInputError("Jev 端点校验失败（HTTP 422）：%s" % body)
            raise JevUnavailable("HTTP %d：%s" % (exc.code, body))
        except OSError as exc:
            # URLError / socket.timeout / TimeoutError / ConnectionError 都是 OSError 子类，
            # 统一转成"暂不可用"，让上层走离线回退而不是报错
            raise JevUnavailable("网络错误：%s" % exc)
        try:
            return json.loads(raw)
        except ValueError:
            # 网关/代理返回 200 但 body 是 HTML 错误页之类
            raise JevUnavailable("响应不是合法 JSON（可能是网关错误页）：%s" % raw[:200])

    try:
        return _once()
    except _RetryableHTTP:
        time.sleep(1.5)
        try:
            return _once()
        except _RetryableHTTP as exc:
            raise JevUnavailable("限流/过载（HTTP %d），重试一次仍失败" % exc.code)
        except JevUnavailable:
            raise


class JevUnavailable(Exception):
    """Jev 暂不可用（无密钥/网络/限流/超时），调用方应走离线回退。"""


class _RetryableHTTP(Exception):
    def __init__(self, code, body):
        super(_RetryableHTTP, self).__init__("HTTP %d：%s" % (code, body))
        self.code = code


# ---------------------------------------------------------------------------
# 四个工具的实现
# ---------------------------------------------------------------------------

_ROUTE_FALLBACK = ("Jev 离线，自行判定等级。参考：改文字/变量名/单文件小改=quick；"
                   "普通 Bug/业务逻辑/少量多文件=medium；跨模块/疑难调试/数据库一致性/安全审查=high；"
                   "复杂架构与疑难杂症=xhigh。拿不准时宁可上调一档。")


def tool_jev_route(state):
    state = _require_state(state)
    _assert_no_secrets(state)
    endpoint, api_key, model, _provider, _reason = _resolve_backend()
    if not api_key:
        return _offline(_reason or "后端不可用",_ROUTE_FALLBACK)

    questions = {
        "route": {
            "type": "choice",
            "instructions": "根据软件开发任务的复杂度、影响范围和推理要求，选择最合适的执行等级。",
            "criteria": {
                "quick": "非常简单、明确的小修改。例如改文字、变量名、小型单文件修改。",
                "medium": "常规软件开发任务。例如普通 Bug、业务逻辑、少量多文件修改。",
                "high": "复杂开发任务。例如跨模块修改、疑难调试、数据库一致性、安全相关代码审查。",
                "xhigh": "非常复杂的软件工程或架构问题，需要最高等级深入推理。",
            },
        },
    }
    result = _post_decisions(endpoint, api_key, model, state, questions)
    answer = (result.get("answers") or {}).get("route") or {}
    level = answer.get("choice")
    if level not in ("quick", "medium", "high", "xhigh"):
        raise JevUnavailable("route 答案异常：%s" % json.dumps(answer, ensure_ascii=False)[:300])
    return {
        "jev": "ok",
        "model": result.get("model"),
        "level": level,
        "probabilities": answer.get("probabilities"),
        "confidence": answer.get("confidence"),
        "usage": result.get("usage"),
    }


_GRILL_FALLBACK = ("Jev 离线，按以下规则自行过滤：能从代码/配置/文档查到的→inspect_code 自己查；"
                   "有明显安全默认值的→infer_safely 采用并记为假设；对实现无实质影响的→unnecessary；"
                   "重复的→duplicate；仅剩会实质影响业务规则/架构/行为/兼容性/安全/验收且无法自行推断的→ask_user。"
                   "并在呈现问题时注明 Jev 离线、由你自行过滤。")


def _parse_grill_items(raw):
    data = raw
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(raw)
        except Exception:
            raise ToolInputError(
                'questions 必须是 JSON 数组（或其文本），例如：'
                '[{"question":"用哪种存储？","recommendation":"沿用 MySQL"},{"question":"..."}] 或 ["问题1","问题2"]')
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ToolInputError("questions 不能为空，且必须是数组（每项为字符串或 {question, recommendation} 对象）")
    items = []
    for index, entry in enumerate(data, 1):
        if isinstance(entry, str) and entry.strip():
            items.append({"question": entry.strip(), "recommendation": None})
        elif isinstance(entry, dict) and entry.get("question"):
            items.append({
                "question": str(entry["question"]),
                "recommendation": entry.get("recommendation"),
            })
        else:
            raise ToolInputError("第 %d 个条目格式错误：需要字符串或含 question 字段的对象" % index)
    return items, len(data) > GRILL_MAX_ITEMS


def tool_jev_grill(state, questions_raw):
    state = _require_state(state)
    items, truncated = _parse_grill_items(questions_raw)
    if truncated:
        items = items[:GRILL_MAX_ITEMS]
    joined = state + " " + " ".join(
        (it["question"] + " " + str(it["recommendation"] or "")) for it in items)
    _assert_no_secrets(joined)
    endpoint, api_key, model, _provider, _reason = _resolve_backend()
    if not api_key:
        return _offline(_reason or "后端不可用",_GRILL_FALLBACK)

    classification = {
        "ask_user": "答案会实质影响业务规则、架构、实现行为、兼容性、安全策略或验收标准，"
                    "且无法从代码和文档推断，必须由用户拍板。",
        "inspect_code": "可以通过阅读仓库源码、配置或文档自行确定，不应打扰用户。",
        "infer_safely": "存在明显安全合理的默认做法，可直接采用推荐值并作为假设记录在计划中。",
        "unnecessary": "对实现路径没有实质影响，问了只是噪音。",
        "duplicate": "与其他候选问题重复，或已被其他问题覆盖。",
    }
    rec_validation = {
        "accept": "推荐答案安全合理，可以直接采用。",
        "revise": "推荐答案存在缺陷或风险，需要修正后才能呈现给用户。",
        "no_safe_default": "不存在安全的默认值，应交由用户明确决定，不宜预设推荐。",
    }

    questions = {}
    for index, item in enumerate(items, 1):
        # decisions API 只把 instructions+criteria 送给模型（问题 key 不发送），
        # 因此每条候选的具体内容必须内联进各自的 instructions，否则模型无法区分条目、答案会互相复制
        recommendation_text = ("推荐答案：%s" % item["recommendation"]) if item["recommendation"] else "（无推荐答案）"
        questions["q%d" % index] = {
            "type": "choice",
            "instructions": "候选澄清问题：%s\n%s\n判断该候选问题最合适的处置方式。"
                % (item["question"], recommendation_text),
            "criteria": classification,
        }
        if item["recommendation"]:
            questions["r%d" % index] = {
                "type": "choice",
                "instructions": "候选问题「%s」的推荐答案是「%s」，该推荐的质量如何？"
                    % (item["question"], item["recommendation"]),
                "criteria": rec_validation,
            }

    result = _post_decisions(endpoint, api_key, model,
                             {"task": state, "candidates": [it["question"] for it in items]},
                             questions)
    answers = result.get("answers") or {}

    out_items = []
    for index, item in enumerate(items, 1):
        q_answer = answers.get("q%d" % index) or {}
        r_answer = answers.get("r%d" % index) or {}
        entry = {
            "question": item["question"],
            "recommendation": item["recommendation"],
            "classification": q_answer.get("choice"),
            "confidence": q_answer.get("confidence"),
        }
        if item["recommendation"]:
            entry["recommendation_check"] = r_answer.get("choice")
        out_items.append(entry)

    return {
        "jev": "ok",
        "model": result.get("model"),
        "results": out_items,
        "usage": result.get("usage"),
        "note": ("候选问题超过 %d 个，已截断至前 %d 个，请分批调用" % (GRILL_MAX_ITEMS, GRILL_MAX_ITEMS))
                if truncated else None,
    }


_RISK_FALLBACK = ("Jev 离线，自行从严判定：凡涉及 DROP/TRUNCATE/大量 DELETE/大量文件删除/force push/"
                  "生产变更/可能丢数据的操作，一律视为危险，先向用户显式确认后再执行。")


_IMPORTANCE_LEVELS = {
    "critical": "不验证就宣布完成属于重大失职的路径（验收标准、安全边界、数据完整性）。",
    "high": "重要但出问题容易被发现的行为（核心业务规则、关键状态迁移）。",
    "normal": "常规功能行为，失败影响可控。",
    "low": "边缘路径或纯辅助行为。",
}

_CAPTURE_DECISIONS = {
    "must_capture": "不留下证据就无法向用户证明该需求已验证，必须留证。",
    "recommended_capture": "留证有价值但并非硬性要求。",
    "no_capture": "测试输出/日志即可覆盖，无需额外取证。",
}

_EVIDENCE_CRITERIA = {
    "screenshot": "用户可见的最终 UI 结果、错误弹窗、布局渲染问题、权限状态。",
    "video": "需要展示过程/时序/交互链路时。",
    "console_output": "命令行执行结果本身即证据。",
    "test_output": "测试框架原始输出（pytest 等）比截图更好。",
    "log": "服务端日志中的事件、标识、决策与结果动作。",
    "api_response": "接口请求/响应 payload。",
    "database_query": "操作前后的精确行/状态。",
    "file_diff": "git diff 等文件级变更。",
    "configuration": "配置项生效情况。",
    "network_trace": "需要证明网络层行为时。",
    "no_extra_evidence": "通过断言即可，无需额外证据。",
}

_REVIEW_FALLBACK = ("Jev 离线，自行按规则评定：重要性看验收价值与失败后果；"
                    "must_capture 仅留给'不留证据就无法证明'的检查点；"
                    "证据类型优先结构化证据（test_output/log/api_response/database_query/file_diff），"
                    "只有视觉状态本身重要时才 screenshot。并在报告中注明 Jev 离线、由你自行评定。")


def _parse_review_items(raw):
    data = raw
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(raw)
        except Exception:
            raise ToolInputError(
                'checkpoints 必须是 JSON 数组（或其文本），例如：'
                '[{"checkpoint":"登录失败时锁定账户","why":"安全验收标准"}] 或 ["检查点1","检查点2"]')
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ToolInputError("checkpoints 不能为空，且必须是数组（每项为字符串或 {checkpoint, why} 对象）")
    items = []
    for index, entry in enumerate(data, 1):
        if isinstance(entry, str) and entry.strip():
            items.append({"checkpoint": entry.strip(), "why": None})
        elif isinstance(entry, dict) and entry.get("checkpoint"):
            items.append({"checkpoint": str(entry["checkpoint"]),
                          "why": entry.get("why")})
        else:
            raise ToolInputError("第 %d 个条目格式错误：需要字符串或含 checkpoint 字段的对象" % index)
    return items, len(data) > GRILL_MAX_ITEMS


def tool_jev_review(state, checkpoints_raw):
    state = _require_state(state)
    items, truncated = _parse_review_items(checkpoints_raw)
    if truncated:
        items = items[:GRILL_MAX_ITEMS]
    joined = state + " " + " ".join(
        (it["checkpoint"] + " " + str(it["why"] or "")) for it in items)
    _assert_no_secrets(joined)
    endpoint, api_key, model, _provider, _reason = _resolve_backend()
    if not api_key:
        return _offline(_reason or "后端不可用",_REVIEW_FALLBACK)

    questions = {}
    for index, item in enumerate(items, 1):
        # 同 jev_grill：每条检查点内容必须内联进各自 instructions，模型才能逐条区分
        why_text = ("理由：%s" % item["why"]) if item["why"] else ""
        base = "测试检查点：%s%s" % (item["checkpoint"], ("\n" + why_text) if why_text else "")
        questions["imp%d" % index] = {
            "type": "choice",
            "instructions": base + "\n判断其重要性等级。",
            "criteria": _IMPORTANCE_LEVELS,
        }
        questions["cap%d" % index] = {
            "type": "choice",
            "instructions": base + "\n判断是否需要额外留证。",
            "criteria": _CAPTURE_DECISIONS,
        }
        questions["ev%d" % index] = {
            "type": "choice",
            "instructions": base + "\n选择证明它的最合适的首要证据类型。",
            "criteria": _EVIDENCE_CRITERIA,
        }

    result = _post_decisions(endpoint, api_key, model,
                             {"task": state, "checkpoints": [it["checkpoint"] for it in items]},
                             questions)
    answers = result.get("answers") or {}

    out_items = []
    for index, item in enumerate(items, 1):
        imp = answers.get("imp%d" % index) or {}
        cap = answers.get("cap%d" % index) or {}
        ev = answers.get("ev%d" % index) or {}
        out_items.append({
            "checkpoint": item["checkpoint"],
            "why": item["why"],
            "importance": imp.get("choice"),
            "importance_confidence": imp.get("confidence"),
            "capture": cap.get("choice"),
            "capture_confidence": cap.get("confidence"),
            "evidence_type": ev.get("choice"),
        })

    return {
        "jev": "ok",
        "model": result.get("model"),
        "results": out_items,
        "usage": result.get("usage"),
        "note": ("候选检查点超过 %d 个，已截断至前 %d 个，请分批调用" % (GRILL_MAX_ITEMS, GRILL_MAX_ITEMS))
                if truncated else None,
    }


def tool_jev_risk(state):
    state = _require_state(state)
    _assert_no_secrets(state)
    endpoint, api_key, model, _provider, _reason = _resolve_backend()
    if not api_key:
        return _offline(_reason or "后端不可用",_RISK_FALLBACK)

    questions = {
        "dangerous": {
            "type": "noul",
            "instructions": "该操作是否具有明显的数据丢失、服务中断、不可逆修改或大范围破坏风险？",
            "criteria": {
                "true": "可能丢失数据、中断服务、产生不可逆修改或大范围破坏。",
                "false": "常规可逆操作，风险可控。",
            },
        },
    }
    result = _post_decisions(endpoint, api_key, model, state, questions)
    answer = (result.get("answers") or {}).get("dangerous") or {}
    if "noul" not in answer:
        raise JevUnavailable("dangerous 答案异常：%s" % json.dumps(answer, ensure_ascii=False)[:300])
    probability = float(answer["noul"])
    return {
        "jev": "ok",
        "model": result.get("model"),
        "dangerous": probability >= 0.5,
        "probability": probability,
        "usage": result.get("usage"),
        "note": "dangerous=true 时必须先获得用户显式确认才可执行；false 仍需遵守 ZCode 权限机制。",
    }


_COMPLETE_FALLBACK = ("Jev 离线，自行按证据判定完成度：逐项核对批准范围是否全部 DONE、关键路径是否有"
                      "测试或运行证据、是否存在未解释的失败；任何一项存疑就降级为 PARTIAL，不要宣布 COMPLETE。")


def tool_jev_complete(state):
    state = _require_state(state)
    _assert_no_secrets(state)
    endpoint, api_key, model, _provider, _reason = _resolve_backend()
    if not api_key:
        return _offline(_reason or "后端不可用",_COMPLETE_FALLBACK)

    questions = {
        "completed": {
            "type": "noul",
            "instructions": "根据原始需求、实际修改和测试证据，该任务是否已经真正完成且不存在明显遗漏？",
            "criteria": {
                "true": "批准范围内的工作均已落地并有证据，可以宣布完成。",
                "false": "存在未完成项、未验证的关键路径或已知未解决问题。",
            },
        },
        "thoroughness": {
            "type": "score",
            "instructions": "该任务的完成质量与证据充分程度处于哪一档？",
            "criteria": [
                "有重大遗漏，不应宣布完成",
                "基本完成，但存在明显未验证项",
                "基本完成，细节可后续跟进",
                "完整且证据充分，可放心宣布完成",
            ],
        },
    }
    result = _post_decisions(endpoint, api_key, model, state, questions)
    answers = result.get("answers") or {}
    completed = answers.get("completed") or {}
    thorough = answers.get("thoroughness") or {}
    if "noul" not in completed:
        raise JevUnavailable("completed 答案异常：%s" % json.dumps(completed, ensure_ascii=False)[:300])
    probability = float(completed["noul"])
    score = thorough.get("score")
    level = None
    if isinstance(score, (int, float)) and thorough.get("legend"):
        level = thorough["legend"].get(str(int(round(score))))
    # 完成门从严：概率 <0.65 一律判未完成；0.50–0.65 的"拿不准"区间附带说明。
    # 风险门(jev_risk)保持 0.5 不变——两个方向的代价不对称，危险侧宁可多确认。
    completed_flag = probability >= 0.65
    note = None
    if 0.5 <= probability < 0.65:
        note = "概率 %.2f 处于不确定区间（0.50–0.65），按未完成处理，建议补充证据后复核" % probability
    return {
        "jev": "ok",
        "model": result.get("model"),
        "completed": completed_flag,
        "probability": probability,
        "note": note,
        "thoroughness": {
            "score": score,
            "level": level,
            "probabilities": thorough.get("probabilities"),
            "confidence": thorough.get("confidence"),
        },
        "usage": result.get("usage"),
    }


def _require_state(state):
    if not state or not state.strip():
        raise ToolInputError("state 不能为空：请提供精简任务摘要（≤10 行），不要发送整个代码库或密钥")
    return state.strip()


def _offline(reason, advice):
    return {"jev": "offline", "reason": reason, "fallback_advice": advice}


# ---------------------------------------------------------------------------
# MCP 工具描述（JSON Schema）
# ---------------------------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "jev_route",
        "description": "开工前判断软件开发任务复杂度并推荐执行等级（quick/medium/high/xhigh）。"
                       "state 提供精简任务摘要、涉及模块和风险点；不要提供密码、Token 或敏感凭据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "精简任务摘要（≤10 行）"},
            },
            "required": ["state"],
        },
    },
    {
        "name": "jev_grill",
        "description": "规划期批量过滤候选澄清问题。questions 为 JSON 数组（文本或直接传数组均可），每项是字符串或"
                       "{question, recommendation} 对象；一次批量传入所有候选（≤20 个）。"
                       "返回每问的处置分类（ask_user/inspect_code/infer_safely/unnecessary/duplicate）"
                       "与推荐答案校验（accept/revise/no_safe_default）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "任务背景摘要"},
                "questions": {
                    "type": ["string", "array"],
                    "items": {"type": ["string", "object"]},
                    "description": '候选问题数组，例如 [{"question":"...","recommendation":"..."}]，也接受其 JSON 文本',
                },
            },
            "required": ["state", "questions"],
        },
    },
    {
        "name": "jev_review",
        "description": "测试期批量评审候选测试检查点。checkpoints 为 JSON 数组（文本或直接传数组均可），每项是字符串或"
                       "{checkpoint, why} 对象；一次批量传入所有候选（≤20 个）。返回每项的重要性"
                       "（critical/high/normal/low）、留证决策（must_capture/recommended_capture/no_capture）"
                       "与最佳证据类型（screenshot/log/api_response/database_query/file_diff 等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "需求背景与验收标准摘要"},
                "checkpoints": {
                    "type": ["string", "array"],
                    "items": {"type": ["string", "object"]},
                    "description": '检查点数组，例如 [{"checkpoint":"...","why":"..."}]，也接受其 JSON 文本',
                },
            },
            "required": ["state", "checkpoints"],
        },
    },
    {
        "name": "jev_risk",
        "description": "判断即将执行的操作是否具有较高破坏性风险（数据丢失/服务中断/不可逆/大范围破坏）。"
                       "在 DROP、TRUNCATE、大量 DELETE、大量文件删除、force push、生产环境变更之前调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "即将执行的操作的精简描述"},
            },
            "required": ["state"],
        },
    },
    {
        "name": "jev_complete",
        "description": "宣布任务完成前的最终判断。state 应包含：原始需求、批准的计划、实际修改、"
                       "已执行的测试与结果、失败/跳过的测试、未解决问题与已知风险。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "完成度摘要（需求/修改/测试/遗留）"},
            },
            "required": ["state"],
        },
    },
]

_TOOL_FUNCS = {
    "jev_route": lambda args: tool_jev_route(args.get("state", "")),
    "jev_grill": lambda args: tool_jev_grill(args.get("state", ""), args.get("questions", "")),
    "jev_review": lambda args: tool_jev_review(args.get("state", ""), args.get("checkpoints", "")),
    "jev_risk": lambda args: tool_jev_risk(args.get("state", "")),
    "jev_complete": lambda args: tool_jev_complete(args.get("state", "")),
}

_TOOL_FALLBACKS = {
    "jev_route": _ROUTE_FALLBACK,
    "jev_grill": _GRILL_FALLBACK,
    "jev_review": _REVIEW_FALLBACK,
    "jev_risk": _RISK_FALLBACK,
    "jev_complete": _COMPLETE_FALLBACK,
}


# ---------------------------------------------------------------------------
# MCP stdio 协议（换行分隔 JSON-RPC 2.0）
# ---------------------------------------------------------------------------

def _rpc_result(result):
    return {"jsonrpc": "2.0", "result": result}


def handle_request(method, params):
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION_DEFAULT,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOL_SPECS}
    if method == "tools/call":
        name = params.get("name") or ""
        func = _TOOL_FUNCS.get(name)
        if func is None:
            return {
                "content": [{"type": "text", "text": "未知工具：%s" % name}],
                "isError": True,
            }
        try:
            output = func(params.get("arguments") or {})
            return {
                "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False, indent=2)}],
                "isError": False,
            }
        except JevRefused as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except ToolInputError as exc:
            return {"content": [{"type": "text", "text": "参数错误：%s" % exc}], "isError": True}
        except JevAuthError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except JevUnavailable as exc:
            # 契约：无密钥/网络失败/超时/限流重试后仍失败/答案形状异常 → 统一离线回退，isError=false，
            # 让调用方按 fallback_advice 自行判定；只有认证失败(401/403)和参数错误才走 isError
            offline = {
                "jev": "offline",
                "reason": str(exc),
                "fallback_advice": _TOOL_FALLBACKS.get(name, "Jev 离线，自行判定并在结果中注明。"),
            }
            return {
                "content": [{"type": "text", "text": json.dumps(offline, ensure_ascii=False, indent=2)}],
                "isError": False,
            }
    raise MethodNotFound(method)


class MethodNotFound(Exception):
    pass


def serve():
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")  # Windows 默认 GBK，必须切到 UTF-8
        except Exception:
            pass
    _log("jev_mcp 启动（stdio JSON-RPC），工具：%s" % ", ".join(t["name"] for t in TOOL_SPECS))
    endpoint, api_key, model, provider, _reason = _resolve_backend()
    if api_key:
        _log("后端：%s（%s，模型 %s）" % (provider, endpoint, model))
    else:
        _log("未配置可用密钥（%s），全部工具将走离线回退" % (_reason or "未知原因"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _log("忽略无法解析的行：%s" % line[:120])
            continue
        if not isinstance(message, dict):
            continue
        request_id = message.get("id")
        if request_id is None:
            continue  # 通知不需要响应
        method = message.get("method") or ""
        try:
            reply = dict(_rpc_result(handle_request(method, message.get("params") or {})), id=request_id)
        except MethodNotFound:
            reply = {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32601, "message": "Method not found: %s" % method}}
        except Exception as exc:  # 兜底：任何异常都不能让 server 崩掉
            reply = {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32603, "message": "Internal error: %s" % exc}}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
