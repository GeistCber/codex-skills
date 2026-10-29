"""Validate a run and render offline reports. Never executes tests or desktop input."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
from html import escape
import importlib.util
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sys
from urllib.parse import quote


STATUSES = {"Passed", "Failed", "NotRun", "Blocked", "Error"}
PHASES = {"inventory", "planning", "preflight", "desktop", "supplement", "fixing",
          "reporting", "paused", "finished"}
CONTROLS = {"background", "desktop", "paused", "released"}
KINDS = {"requirement": "需求", "resource": "资源关系", "combination": "完整组合", "workflow": "工作流"}
METHODS = {"desktop_ui": "真实界面实操", "window_integration": "窗口集成",
           "host": "宿主验证", "script": "补充脚本"}
LABELS = {"Passed": "通过", "Failed": "失败", "NotRun": "未测", "Blocked": "阻塞",
          "Error": "执行错误", "Incomplete": "未完成", "Demo": "报告演示（非实测）",
          "PassedWithinScope": "声明范围内通过", "deferred": "暂缓",
          "not_applicable": "不适用"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}


class ReportError(ValueError):
    """Malformed or untrustworthy report data."""


def need(condition, message):
    if not condition:
        raise ReportError(message)


def words(obj, *keys):
    need(isinstance(obj, dict), "Expected an object")
    for key in keys:
        need(isinstance(obj.get(key), str) and bool(obj[key].strip()), f"Missing text: {key}")


def array(obj, key):
    need(isinstance(obj.get(key), list), f"Expected array: {key}")
    return obj[key]


def indexed(rows, label):
    result = {}
    for row in rows:
        words(row, "id")
        need(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", row["id"])),
             f"Use stable ASCII ID for {label}: {row['id']}")
        need(row["id"] not in result, f"Duplicate {label} ID: {row['id']}")
        result[row["id"]] = row
    return result


def local_file(root, value):
    need(isinstance(value, str) and bool(value), "Missing attachment path")
    winpath = PureWindowsPath(value)
    need(not winpath.drive and not winpath.root and "\\" not in value,
         f"Attachment must use a relative forward-slash path: {value}")
    path = (root / value).resolve()
    need(path.is_relative_to(root.resolve()) and path.is_file(), f"Missing/outside attachment: {value}")
    return path


def state(case):
    return case["attempts"][-1]["status"] if case["attempts"] else "NotRun"


def recovered(case):
    return state(case) == "Passed" and any(a["status"] in {"Failed", "Error"} for a in case["attempts"][:-1])


def timestamp(value):
    try:
        at = datetime.fromisoformat(value)
        need(at.utcoffset() is not None, "Timestamps need a timezone")
        return at
    except (TypeError, ValueError):
        raise ReportError("Invalid timestamp or missing timezone") from None


def fingerprint(value):
    need(isinstance(value, str) and bool(re.fullmatch(r"[a-fA-F0-9]{64}", value)),
         "Real runs need SHA256 fingerprints")


def validate(data, root):
    need(isinstance(data, dict), "Run must be an object")
    need(type(data.get("schema_version")) is int and data["schema_version"] == 1,
         "Unsupported schema_version")
    words(data, "run_id", "title", "project", "phase", "control")
    need(data["phase"] in PHASES and data["control"] in CONTROLS, "Invalid lifecycle state")
    need(type(data.get("is_demo")) is bool, "is_demo must be boolean")
    inventory = data.get("inventory")
    words(inventory, "strategy")
    need(type(inventory.get("complete")) is bool, "inventory.complete must be boolean")
    need(bool(array(inventory, "sources")), "Inventory needs independent sources")
    words(data.get("build"), "revision", "dirty_state", "artifact_sha256", "config")
    if not data["is_demo"]:
        fingerprint(data["build"]["artifact_sha256"])
    for entry in array(data, "inputs"):
        words(entry, "path", "sha256")
        if not data["is_demo"]:
            fingerprint(entry["sha256"])
    previous_event = None
    for event in array(data, "events"):
        words(event, "at", "phase", "control", "notice")
        need(event["phase"] in PHASES and event["control"] in CONTROLS, "Invalid event state")
        at = timestamp(event["at"])
        need(previous_event is None or at >= previous_event, "Events must be chronological")
        previous_event = at
    need(all(isinstance(v, str) for v in array(data, "limitations")), "Invalid limitations")
    attachments = indexed(array(data, "attachments"), "attachment")
    for att in attachments.values():
        words(att, "path", "kind", "caption")
        need(att["kind"] in {"desktop_screenshot", "native_export", "reference", "log", "illustration"},
             "Invalid attachment kind")
        path = local_file(root, att["path"])
        if att.get("sha256"):
            fingerprint(att["sha256"])
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            need(actual.lower() == att["sha256"].lower(), f"Attachment hash mismatch: {att['id']}")
    cases = indexed(array(data, "cases"), "case")
    for case in cases.values():
        words(case, "title", "method", "purpose")
        need(case["method"] in METHODS, "Invalid test method")
        need(case["purpose"] in {"acceptance", "diagnostic"}, "Invalid case purpose")
        need(isinstance(case.get("parameters"), dict), "Missing parameters object")
        need(all(isinstance(v, str) for v in array(case, "preconditions")), "Invalid preconditions")
        need(bool(array(case, "steps")), f"Case has no steps: {case['id']}")
        need(all(isinstance(v, str) and v.strip() for v in case["steps"]), "Invalid steps")
        words(case.get("expected"), "source", "description")
        attempts = indexed(array(case, "attempts"), "attempt")
        previous_attempt = None
        for attempt in attempts.values():
            words(attempt, "at", "status", "observed")
            at = timestamp(attempt["at"])
            need(previous_attempt is None or at >= previous_attempt, "Attempts must be chronological")
            previous_attempt = at
            need(attempt["status"] in STATUSES, "Invalid attempt status")
            need(isinstance(attempt.get("review", {}), dict), "Invalid review object")
            evidence = array(attempt, "evidence")
            need(all(isinstance(v, str) and v in attachments for v in evidence),
                 f"Unknown evidence in {case['id']}")
            if attempt["status"] == "Passed":
                need(bool(evidence), f"Passed case has no evidence: {case['id']}")
                review = attempt.get("review")
                words(review, "outcome", "note")
                need(review["outcome"] == "matched", "Passed review must be matched")
                if case["method"] == "desktop_ui" and not data["is_demo"]:
                    need(any(attachments[v]["kind"] == "desktop_screenshot"
                             and Path(attachments[v]["path"]).suffix.lower() in IMAGE_SUFFIXES
                             for v in evidence), f"Desktop pass lacks real screenshot: {case['id']}")
            else:
                words(attempt, "reason")
    coverage = indexed(array(data, "coverage"), "coverage")
    for item in coverage.values():
        words(item, "kind", "title", "scope")
        need(item["kind"] in KINDS and item["scope"] in {"in", "deferred", "not_applicable"},
             "Invalid coverage kind/scope")
        ids = array(item, "required_case_ids")
        need(all(isinstance(v, str) and v in cases for v in ids), "Unknown required case")
        need(len(ids) == len(set(ids)), "Duplicate required case")
        need(all(cases[v]["purpose"] == "acceptance" for v in ids),
             "Diagnostic case cannot satisfy acceptance coverage")
        if item["scope"] == "in":
            need(bool(ids), f"In-scope item needs required cases: {item['id']}")
        else:
            words(item, "reason")
    if any(c["method"] == "desktop_ui" and c["attempts"] for c in cases.values()) and not data["is_demo"]:
        words(data.get("desktop"), "authorization", "target", "limits", "stop")
        need(any(e["control"] == "desktop" for e in data["events"]),
             "Desktop attempts need an actual takeover notification record")
    if data.get("profile"):
        need(data["profile"] == "functional-v1", "Unknown acceptance profile")
        validate_functional(data, root)
    return data


def validate_functional(data, root):
    spec = importlib.util.spec_from_file_location("testing_session", Path(__file__).with_name("session.py"))
    session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(session)
    plan = data.get("plan")
    words(plan, "path", "sha256", "frozen_at")
    fingerprint(plan["sha256"])
    frozen = local_file(root, plan["path"])
    need(hashlib.sha256(frozen.read_bytes()).hexdigest() == plan["sha256"], "Frozen plan hash differs")
    payload = json.loads(frozen.read_text(encoding="utf-8-sig"))
    need(payload.get("payload") == session.plan_payload(data), "Plan changed after freeze; start a linked run")
    need(payload.get("frozen_at") == plan["frozen_at"], "Plan time differs")
    frozen_at = timestamp(plan["frozen_at"])
    events = data["events"]
    need(bool(events), "Functional runs need lifecycle events")
    need(events[-1]["phase"] == data["phase"] and events[-1]["control"] == data["control"],
         "Current lifecycle differs from the last event")
    for previous, event in zip([None] + events[:-1], events):
        need(session.CONTROLS[event["phase"]] == event["control"], "Incompatible phase/control")
        if previous and previous["phase"] == "finished":
            need(False, "Finished run has subsequent events")
        if previous and previous["control"] == "paused" and event["phase"] not in {"paused", "finished"}:
            need(event.get("resume_authorized") is True, "Resume authorization missing")
    phases = [e["phase"] for e in events]
    for required in ("inventory", "planning", "preflight"):
        need(required in phases, f"Missing lifecycle phase: {required}")
    need(phases.index("inventory") < phases.index("planning") < phases.index("preflight"),
         "Inventory/planning/preflight order is invalid")
    need(timestamp(events[phases.index("planning")]["at"]) <= frozen_at,
         "Plan was frozen before planning")
    case_ids = {c["id"] for c in data["cases"]}
    dimensions = array(data["inventory"], "dimensions")
    need(bool(dimensions), "Declare parameter dimensions or an explicit not-applicable dimension")
    indexed(dimensions, "dimension")
    for dimension in dimensions:
        words(dimension, "title", "strategy")
        selected = array(dimension, "selected")
        uncovered = array(dimension, "uncovered")
        need(bool(selected or uncovered), "Dimension has no selected or uncovered values")
        for value in selected:
            words(value, "value")
            ids = array(value, "case_ids")
            need(bool(ids) and all(cid in case_ids for cid in ids), "Dimension references no/unknown cases")
        for value in uncovered:
            words(value, "value", "reason")
    for case in data["cases"]:
        checks = indexed(array(case["expected"], "checks"), "criterion")
        need(bool(checks), f"Case needs concrete criteria: {case['id']}")
        for check in checks.values():
            words(check, "description")
            need("target" in check, "Criterion target is missing")
            if type(check["target"]) in (int, float):
                tolerance = check.get("tolerance", 0)
                need(type(tolerance) in (int, float) and math.isfinite(tolerance) and tolerance >= 0,
                     "Invalid numeric tolerance")
                need(math.isfinite(check["target"]), "Invalid numeric target")
        for attempt in case["attempts"]:
            origin = attempt.get("evidence_origin", "current")
            need(origin in {"current", "historical"}, "Invalid evidence origin")
            if origin == "historical":
                words(attempt, "evidence_run", "reuse_reason")
            else:
                need(timestamp(attempt["at"]) >= frozen_at, "Attempt predates the frozen plan")
            actual = indexed(attempt.get("checks", []), "actual criterion")
            need(all(cid in checks for cid in actual), "Unknown actual criterion")
            if attempt["status"] == "Passed":
                need(set(actual) == set(checks), "Passed attempt has missing criteria")
            for cid, value in actual.items():
                need(value.get("status") in STATUSES and "value" in value, "Invalid actual criterion")
                if attempt["status"] == "Passed":
                    need(value["status"] == "Passed", "Passed attempt contains a non-passing criterion")
                if value["status"] == "Passed":
                    expected = checks[cid]
                    target, observed = expected["target"], value["value"]
                    if type(target) in (int, float):
                        matched = (type(observed) in (int, float) and math.isfinite(observed)
                                   and abs(observed - target) <= expected.get("tolerance", 0))
                    else:
                        matched = type(target) is type(observed) and observed == target
                    need(matched, f"Passing criterion differs from target: {case['id']}/{cid}")


def item_state(item, cases):
    if item["scope"] != "in":
        return item["scope"]
    statuses = [state(cases[v]) for v in item["required_case_ids"]]
    for status in ("Error", "Failed", "Blocked", "NotRun"):
        if status in statuses:
            return status
    if any(recovered(cases[v]) for v in item["required_case_ids"]):
        return "Blocked"
    return "Passed"


def conclusion(data):
    if data["is_demo"]:
        return "Demo"
    statuses = [state(c) for c in data["cases"]]
    if any(s in {"Failed", "Error"} for s in statuses):
        return "Failed"
    in_scope = [i for i in data["coverage"] if i["scope"] == "in"]
    if (not in_scope or not any(c["purpose"] == "acceptance" for c in data["cases"])
            or not data["inventory"]["complete"] or not statuses
            or any(s != "Passed" for s in statuses)
            or any(recovered(c) for c in data["cases"])
            or data["phase"] != "finished" or data["control"] != "released"):
        return "Incomplete"
    return "PassedWithinScope" if any(i["scope"] != "in" for i in data["coverage"]) else "Passed"


def summary(data):
    cases = {c["id"]: c for c in data["cases"]}
    stats = {}
    for kind in KINDS:
        rows = [i for i in data["coverage"] if i["kind"] == kind]
        scoped = [i for i in rows if i["scope"] == "in"]
        stats[kind] = {"passed": sum(item_state(i, cases) == "Passed" for i in scoped),
                       "total": len(scoped), "outside": len(rows) - len(scoped)}
    return {"run_id": data["run_id"], "conclusion": conclusion(data), "coverage": stats,
            "cases": dict(Counter(state(c) for c in data["cases"])),
            "acceptance": dict(Counter(state(c) for c in data["cases"] if c["purpose"] == "acceptance")),
            "diagnostic": dict(Counter(state(c) for c in data["cases"] if c["purpose"] == "diagnostic"))}


def counts_text(cases):
    rows = list(cases)
    counts = Counter(state(c) for c in rows if not recovered(c))
    retry = sum(recovered(c) for c in rows)
    parts = [f"{'通过（无失败重试）' if s == 'Passed' else LABELS[s]} {count}" for s, count in counts.items()]
    if retry:
        parts.append(f"重试后通过、稳定性待复核 {retry}")
    return " · ".join(parts) or "无用例"


def plain(value):
    return json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)


def md_text(value):
    value = escape(plain(value), quote=False).replace("|", "&#124;").replace("\r", "").replace("\n", "<br>")
    for ch in "\\[]()*_`!#":
        value = value.replace(ch, "\\" + ch)
    return value


def md_block(value):
    text = plain(value)
    fence = "`" * max(3, max((len(m.group()) for m in re.finditer(r"`+", text)), default=0) + 1)
    return f"{fence}json\n{text}\n{fence}"


def criteria_rows(case, attempt):
    actual = {v["id"]: v for v in attempt.get("checks", [])}
    for check in case["expected"].get("checks", []):
        value = actual.get(check["id"], {})
        yield [check["description"], plain(check["target"]) + (" " + check["unit"] if check.get("unit") else ""),
               plain(value["value"]) if "value" in value else "未核对",
               LABELS.get(value.get("status"), "未测")]


def render_markdown(data):
    info = summary(data)
    cases = {c["id"]: c for c in data["cases"]}
    attachments = {a["id"]: a for a in data["attachments"]}
    out = [f"# {md_text(data['title'])}", "", f"**{LABELS[info['conclusion']]}** · {md_text(data['run_id'])}", "",
           f"项目：{md_text(data['project'])}；阶段：{data['phase']}；桌面：{data['control']}。", "",
           f"验收用例：{counts_text(c for c in data['cases'] if c['purpose'] == 'acceptance')}。", "",
           "规范：" + ("功能级 functional-v1（计划冻结及逐点核对）" if data.get("profile") else "历史兼容格式；未验证新功能级规范。"), "",
           "覆盖率仅针对声明清单；断言数量不代表业务覆盖率。演示数据不作为实测证据。", "",
           "## 覆盖矩阵", "", "| 类型 | 通过 / 范围内 | 范围外（另列） |", "|---|---|---|"]
    for kind, row in info["coverage"].items():
        out.append(f"| {KINDS[kind]} | {row['passed']} / {row['total']} | {row['outside']} |")
    out += ["", "| ID / 项目 | 状态 | 必需验收用例 / 范围说明 |", "|---|---|---|"]
    for item in data["coverage"]:
        details = ", ".join(item["required_case_ids"]) + " " + item.get("reason", "")
        out.append(f"| {md_text(item['id'] + ' ' + item['title'])} | {LABELS[item_state(item, cases)]} | {md_text(details)} |")
    if data["inventory"].get("dimensions"):
        out += ["", "## 参数与场景选择", "", "| 维度 | 本轮选择值 | 关联用例 / 未覆盖原因 |", "|---|---|---|"]
        for dimension in data["inventory"]["dimensions"]:
            for selected in dimension["selected"]:
                out.append(f"| {md_text(dimension['title'])} | {md_text(selected['value'])} | {md_text(', '.join(selected['case_ids']))} |")
            for missing in dimension["uncovered"]:
                out.append(f"| {md_text(dimension['title'])} | 未覆盖：{md_text(missing['value'])} | {md_text(missing['reason'])} |")
    out += ["", "## 测试方式", "", "| 入口 | 用例数（验收 / 诊断） | 状态分布 |", "|---|---|---|"]
    for method, label in METHODS.items():
        rows = [c for c in data["cases"] if c["method"] == method]
        acceptance = sum(c["purpose"] == "acceptance" for c in rows)
        out.append(f"| {label} | {len(rows)}（{acceptance} / {len(rows) - acceptance}） | {counts_text(rows)} |")
    out += ["", "## 范围与限制", ""]
    out += [f"- {md_text(v)}" for v in data["limitations"]] or ["- 无额外记录；仍需审阅覆盖分母。"]
    out += ["", "## 逐例记录", ""]
    for case in data["cases"]:
        out += [f"### {md_text(case['id'] + ' ' + case['title'])} · {LABELS[state(case)]}", "",
                f"入口：{METHODS[case['method']]}；用途：{'验收' if case['purpose'] == 'acceptance' else '诊断'}。", "",
                "参数：", "", md_block(case['parameters']), "", "前提：", "",
                *[f"- {md_text(v)}" for v in case['preconditions']], "",
                "步骤：", ""]
        if recovered(case):
            out += ["**同版本曾失败后重试成功：稳定性待复核，不按无保留通过交付。**", ""]
        out += [f"{i}. {md_text(v)}" for i, v in enumerate(case["steps"], 1)]
        out += ["", f"预期：{md_text(case['expected']['description'])}", "",
                f"独立依据：{md_text(case['expected']['source'])}", ""]
        if not case["attempts"]:
            out += ["尚未执行。", ""]
        for attempt in case["attempts"]:
            out += [f"**{md_text(attempt['id'])} · {LABELS[attempt['status']]} · {md_text(attempt['at'])}**", ""]
            if attempt.get("evidence_origin") == "historical":
                out += [f"历史证据：{md_text(attempt['evidence_run'])}；{md_text(attempt['reuse_reason'])}", ""]
            if case["expected"].get("checks"):
                out += ["| 检查点 | 预期 | 实际 | 结果 |", "|---|---|---|---|"]
                out += ["| " + " | ".join(md_text(v) for v in row) + " |" for row in criteria_rows(case, attempt)]
                out.append("")
            out += [f"实际：{md_text(attempt['observed'])}", "",
                    f"原因 / 核对：{md_text(attempt.get('reason', ''))} {md_text(attempt.get('review', {}).get('note', ''))}", ""]
            for aid in attempt["evidence"]:
                att = attachments[aid]
                url = quote(att["path"], safe="/")
                out += [f"[{md_text(att['caption'])} · {att['kind']}]({url})", ""]
                if Path(att["path"]).suffix.lower() in IMAGE_SUFFIXES:
                    out += [f"![证据 {md_text(aid)}]({url})", ""]
    out += ["## 阶段通知记录", ""]
    out += [f"- {md_text(e['at'])} · {e['phase']} / {e['control']}：{md_text(e['notice'])}" for e in data["events"]]
    out += ["", "## 输入与构建", "", "盘点：", "", md_block(data['inventory']), "",
            "输入：", "", md_block(data['inputs']), "", "构建：", "", md_block(data['build']), ""]
    if data.get("desktop"):
        out += ["桌面约定：", "", md_block(data['desktop']), ""]
    if data.get("previous_run"):
        out += [f"上一轮：{md_text(data['previous_run'])}", ""]
    return "\n".join(out)


def render_html(data):
    info = summary(data)
    cases = {c["id"]: c for c in data["cases"]}
    attachments = {a["id"]: a for a in data["attachments"]}
    esc = lambda v: escape(plain(v), quote=True)
    out = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           f"<title>{esc(data['title'])}</title>",
           "<style>body{font:16px/1.65 system-ui,'Microsoft YaHei',sans-serif;margin:0;background:#f3f5f8;color:#192734}"
           "main{max-width:1120px;margin:auto;padding:32px 24px}h1{font-size:28px}h2{margin-top:32px}"
           "a{color:#175bac}table{border-collapse:collapse;width:100%;background:white;margin:16px 0}"
           "td,th{border:1px solid #d5dce4;padding:10px;text-align:left;vertical-align:top}"
           ".cards{display:flex;gap:14px;flex-wrap:wrap}.card{background:white;padding:14px 20px;border:1px solid #d5dce4;border-radius:8px}"
           ".badge{font-weight:700;padding:3px 9px;border-radius:4px;background:#e8edf2}.Passed,.PassedWithinScope{color:#145e37;background:#e0f2e7}"
           ".Failed,.Error{color:#a02020;background:#ffeded}.NotRun,.Blocked,.Incomplete,.Demo{color:#78520b;background:#fff0cc}"
           "details{background:white;border:1px solid #d5dce4;border-radius:8px;margin:14px 0;padding:14px}summary{cursor:pointer;font-weight:650}"
           ".evidence{display:flex;gap:12px;flex-wrap:wrap}figure{margin:8px 0;flex:1 1 320px;min-width:0;border:1px solid #d5dce4;padding:10px}"
           "img{max-width:100%;height:auto}figcaption{font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f9;padding:12px}"
           "input,select{font:inherit;padding:8px;max-width:100%;margin:8px 8px 8px 0}.muted{color:#52606d}.warning{border-left:4px solid #c28a20;padding:12px;background:#fff7e4}"
           "[hidden]{display:none!important}@media(max-width:650px){main{padding:20px 12px}table{font-size:13px}td,th{padding:6px}}"
           "</style><main>", f"<h1>{esc(data['title'])}</h1>",
           f"<p><span class='badge {info['conclusion']}'>{LABELS[info['conclusion']]}</span> · {esc(data['run_id'])}</p>",
           f"<p>项目：{esc(data['project'])} · 阶段：{data['phase']} · 桌面：{data['control']}</p>",
           f"<p><strong>验收用例：</strong>{counts_text(c for c in data['cases'] if c['purpose'] == 'acceptance')}</p>",
           "<p>规范：" + ("功能级 functional-v1（计划冻结及逐点核对）" if data.get("profile") else "历史兼容格式；未验证新功能级规范。") + "</p>",
           "<p class='warning'>覆盖率仅针对已声明清单。流程结束和脚本全绿不能替代完整业务验收。演示图片不是实测截图。</p>",
           "<p><a href='report.md'>Markdown 报告</a> · <a href='run.json'>原始记录</a> · <a href='#cases'>逐例图片</a></p>",
           "<h2>覆盖概览</h2><div class='cards'>"]
    for kind, row in info["coverage"].items():
        out.append(f"<div class='card'>{KINDS[kind]}<br><strong>{row['passed']} / {row['total']}</strong> 通过<br><small>范围外 {row['outside']} 项</small></div>")
    out += ["</div><table><tr><th>覆盖项</th><th>状态</th><th>必需用例 / 范围说明</th></tr>"]
    for item in data["coverage"]:
        current = item_state(item, cases)
        links = " ".join(f"<a href='#case-{quote(cid, safe='')}'>{esc(cid)}</a>" for cid in item["required_case_ids"])
        out.append(f"<tr><td>{esc(item['id'])} · {esc(item['title'])}</td><td><span class='badge {current}'>{LABELS[current]}</span></td><td>{links} {esc(item.get('reason', ''))}</td></tr>")
    out.append("</table>")
    if data["inventory"].get("dimensions"):
        out.append("<h2>参数与场景选择</h2><table><tr><th>维度</th><th>本轮选择值</th><th>关联用例 / 未覆盖原因</th></tr>")
        for dimension in data["inventory"]["dimensions"]:
            for selected in dimension["selected"]:
                links = " ".join(f"<a href='#case-{quote(cid, safe='')}'>{esc(cid)}</a>" for cid in selected['case_ids'])
                out.append(f"<tr><td>{esc(dimension['title'])}</td><td>{esc(selected['value'])}</td><td>{links}</td></tr>")
            for missing in dimension["uncovered"]:
                out.append(f"<tr><td>{esc(dimension['title'])}</td><td>未覆盖：{esc(missing['value'])}</td><td>{esc(missing['reason'])}</td></tr>")
        out.append("</table>")
    out += ["<h2>测试方式</h2><table><tr><th>入口</th><th>用例数（验收 / 诊断）</th><th>状态分布</th></tr>"]
    for method, label in METHODS.items():
        rows = [c for c in data["cases"] if c["method"] == method]
        acceptance = sum(c["purpose"] == "acceptance" for c in rows)
        out.append(f"<tr><td>{label}</td><td>{len(rows)}（{acceptance} / {len(rows) - acceptance}）</td><td>{counts_text(rows)}</td></tr>")
    out += ["</table><h2>范围与限制</h2><ul>"]
    out += [f"<li>{esc(v)}</li>" for v in data["limitations"]]
    out += ["</ul><h2 id='cases'>逐例记录与图片</h2><label>筛选 <select id='status'><option value=''>全部状态</option>"]
    out += [f"<option value='{s}'>{LABELS[s]}</option>" for s in sorted(STATUSES)]
    out += ["</select></label><label>搜索 <input id='query' placeholder='用例、参数、预期或结果'></label><p id='shown' class='muted'></p>"]
    for case in data["cases"]:
        current = state(case)
        opened = " open" if current != "Passed" or recovered(case) else ""
        out += [f"<details class='case' id='case-{quote(case['id'], safe='')}' data-status='{current}'{opened}>",
                f"<summary><span class='badge {current}'>{LABELS[current]}</span> {esc(case['id'])} · {esc(case['title'])}</summary>",
                f"<p>入口：{METHODS[case['method']]} · 用途：{'验收' if case['purpose'] == 'acceptance' else '诊断'}</p>",
                f"<p>参数</p><pre>{esc(case['parameters'])}</pre><p>前提</p><pre>{esc(case['preconditions'])}</pre><ol>"]
        out += [f"<li>{esc(step)}</li>" for step in case["steps"]]
        out += [f"</ol><p><strong>预期：</strong>{esc(case['expected']['description'])}</p>",
                f"<p class='muted'>独立依据：{esc(case['expected']['source'])}</p>"]
        if recovered(case):
            out.append("<p class='warning'>同版本曾失败后重试成功：稳定性待复核，不按无保留通过交付。</p>")
        if not case["attempts"]:
            out.append("<p>尚未执行；不能作为通过证据。</p>")
        for attempt in case["attempts"]:
            out.append(f"<h3>{esc(attempt['id'])} · {LABELS[attempt['status']]} · {esc(attempt['at'])}</h3>")
            if attempt.get("evidence_origin") == "historical":
                out.append(f"<p class='warning'>历史证据：{esc(attempt['evidence_run'])}；{esc(attempt['reuse_reason'])}</p>")
            if case["expected"].get("checks"):
                out.append("<table><tr><th>检查点</th><th>预期</th><th>实际</th><th>结果</th></tr>")
                for row in criteria_rows(case, attempt):
                    out.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>")
                out.append("</table>")
            out += [f"<p><strong>实际：</strong>{esc(attempt['observed'])}</p>",
                    f"<p>原因 / 核对：{esc(attempt.get('reason', ''))} {esc(attempt.get('review', {}).get('note', ''))}</p><div class='evidence'>"]
            for aid in attempt["evidence"]:
                att = attachments[aid]
                url = quote(att["path"], safe="/")
                out += [f"<figure><figcaption><a href='{url}'>{esc(att['caption'])}</a> · {att['kind']}</figcaption>"]
                if Path(att["path"]).suffix.lower() in IMAGE_SUFFIXES:
                    out += [f"<a href='{url}'><img src='{url}' loading='lazy' alt='{esc(att['caption'])}'></a>"]
                out.append("</figure>")
            out.append("</div>")
        out.append("</details>")
    out += ["<h2>阶段通知记录</h2><ol>"]
    out += [f"<li>{esc(e['at'])} · {e['phase']} / {e['control']}：{esc(e['notice'])}</li>" for e in data["events"]]
    out += ["</ol><h2>输入与构建</h2>", f"<pre>{esc(data['inventory'])}</pre>",
            f"<pre>{esc(data['inputs'])}</pre><pre>{esc(data['build'])}</pre>"]
    if data.get("desktop"):
        out += [f"<h3>桌面约定</h3><pre>{esc(data['desktop'])}</pre>"]
    if data.get("previous_run"):
        out += [f"<p>上一轮：{esc(data['previous_run'])}</p>"]
    out += ["</main><script>const rows=[...document.querySelectorAll('.case')];"
            "function filter(){const s=document.querySelector('#status').value;"
            "const q=document.querySelector('#query').value.toLowerCase();let count=0;"
            "for(const r of rows){r.hidden=!!((s&&r.dataset.status!==s)||(q&&!r.textContent.toLowerCase().includes(q)));if(!r.hidden)count++;}"
            "document.querySelector('#shown').textContent='显示 '+count+' / '+rows.length+' 条用例';}"
            "document.querySelector('#status').addEventListener('change',filter);document.querySelector('#query').addEventListener('input',filter);filter();"
            "function revealCase(hash){const id=decodeURIComponent(hash.slice(1));if(!id.startsWith('case-'))return;"
            "const r=document.getElementById(id);if(!r)return;document.querySelector('#status').value='';document.querySelector('#query').value='';filter();r.open=true;"
            "requestAnimationFrame(()=>r.scrollIntoView({block:'start'}));}"
            "document.querySelectorAll('a[href^=\"#case-\"]').forEach(a=>a.addEventListener('click',()=>revealCase(a.hash)));"
            "window.addEventListener('hashchange',()=>revealCase(location.hash));revealCase(location.hash);"
            "</script></html>"]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate without writing reports")
    parser.add_argument("--require-pass", action="store_true", help="Return 1 unless acceptance passes")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.run.read_text(encoding="utf-8-sig"))
        root = args.run.resolve().parent
        validate(data, root)
        if not args.check:
            (root / "report.md").write_text(render_markdown(data), encoding="utf-8")
            (root / "report.html").write_text(render_html(data), encoding="utf-8")
        result = summary(data)
        print(json.dumps(result, ensure_ascii=False))
        return int(args.require_pass and result["conclusion"] not in {"Passed", "PassedWithinScope"})
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
