"""Step plugins for deterministic scenario orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any
import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from continuum.errors import PluginResolutionError, StepExecutionError


@dataclass(slots=True)
class StepResult:
    ok: bool
    details: dict[str, Any]
    evidence_paths: list[str]
    exports: dict[str, Any] | None = None


class Plugin(Protocol):
    type: str

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        ...


def render_templates(value: Any, *, ctx: dict[str, Any]) -> Any:
    def lookup(path: str) -> Any:
        current: Any = ctx
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return ""
        return current

    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def repl(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key == "runId":
                return str(ctx["run_id"])
            if key == "runDir":
                return str(ctx["run_dir"])
            if key.startswith("env."):
                env_key = key[4:]
                return str(ctx["env"].get(env_key, ""))
            if key.startswith("vars."):
                return str(lookup(key))
            return str(ctx["vars"].get(key, ""))

        return pattern.sub(repl, value)

    if isinstance(value, dict):
        return {k: render_templates(v, ctx=ctx) for k, v in value.items()}

    if isinstance(value, list):
        return [render_templates(v, ctx=ctx) for v in value]

    return value


class AppLauncherStartPlugin:
    type = "applauncher.start"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        command = step_with.get("command")
        args = step_with.get("args", [])
        if not isinstance(command, str) or not command.strip():
            raise StepExecutionError("applauncher.start requires a non-empty with.command")
        if not isinstance(args, list):
            raise StepExecutionError("applauncher.start with.args must be an array")

        cwd = step_with.get("cwd") or str(ctx.get("repo_root") or Path.cwd())
        env = os.environ.copy()
        env.update({k: str(v) for k, v in step_with.get("env", {}).items()})

        process = subprocess.Popen(
            [command, *[str(item) for item in args]],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        ctx["vars"]["__applauncherPid"] = process.pid
        ctx["vars"]["__applauncherCwd"] = cwd

        step_dir = ctx["step_dir"](step_index, step_name)
        out_log = ctx["write"](step_dir, "stdout.log", process.stdout.read(0) if process.stdout else "")
        err_log = ctx["write"](step_dir, "stderr.log", process.stderr.read(0) if process.stderr else "")
        pid_path = ctx["write_json"](
            step_dir,
            "pid.json",
            {"pid": process.pid, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        return StepResult(
            ok=True,
            details={"pid": process.pid},
            evidence_paths=[out_log, err_log, pid_path],
            exports={"applauncherPid": process.pid},
        )


class AppLauncherStopPlugin:
    type = "applauncher.stop"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        pid = step_with.get("pid", ctx["vars"].get("__applauncherPid"))
        if not pid:
            raise StepExecutionError("applauncher.stop could not find a pid")
        try:
            os.kill(int(pid), 15)
        except ProcessLookupError:
            pass

        step_dir = ctx["step_dir"](step_index, step_name)
        out_path = ctx["write_json"](
            step_dir,
            "stopped.json",
            {"pid": int(pid), "stoppedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        return StepResult(ok=True, details={"pid": int(pid)}, evidence_paths=[out_path])


class HttpHealthPlugin:
    type = "http.health"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        url = step_with.get("url")
        timeout_sec = int(step_with.get("timeoutSec", 120))
        if not isinstance(url, str) or not url.strip():
            raise StepExecutionError("http.health requires with.url")

        deadline = time.time() + timeout_sec
        last_error = None
        result: dict[str, Any] = {"ok": False, "url": url}
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    payload = response.read().decode("utf-8", errors="replace")
                    result = {"ok": True, "url": url, "status": response.status, "body": payload}
                    break
            except Exception as err:  # noqa: BLE001
                last_error = str(err)
                time.sleep(1)

        if not result["ok"]:
            result["error"] = last_error or "health check timeout"

        step_dir = ctx["step_dir"](step_index, step_name)
        health_path = ctx["write_json"](step_dir, "health.json", result)
        return StepResult(
            ok=bool(result["ok"]),
            details=result,
            evidence_paths=[health_path],
            exports={"healthOk": bool(result["ok"]), "healthStatus": result.get("status")},
        )


class PostmanRunPlugin:
    type = "postman.run"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        if shutil.which("newman") is None:
            raise StepExecutionError("postman.run requires newman installed and available on PATH")

        collection = step_with.get("collection")
        if not isinstance(collection, str) or not collection.strip():
            raise StepExecutionError("postman.run requires with.collection")

        step_dir = Path(ctx["step_dir"](step_index, step_name))
        step_dir.mkdir(parents=True, exist_ok=True)

        report_json = step_dir / "newman-report.json"
        report_html = step_dir / "newman-report.html"
        console_log = step_dir / "console.log"

        command = [
            "newman",
            "run",
            collection,
            "-r",
            "cli,json,html",
            "--reporter-json-export",
            str(report_json),
            "--reporter-html-export",
            str(report_html),
        ]
        if isinstance(step_with.get("environment"), str):
            command.extend(["--environment", str(step_with["environment"])])

        for key, value in dict(step_with.get("envVar", {})).items():
            command.extend(["--env-var", f"{key}={value}"])

        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        console_log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")

        summary_path = ctx["write_json"](
            str(step_dir),
            "newman-summary.json",
            {"returncode": proc.returncode},
        )
        return StepResult(
            ok=proc.returncode == 0,
            details={"returncode": proc.returncode},
            evidence_paths=[summary_path, str(report_json), str(report_html), str(console_log)],
            exports={
                "newmanHtml": str(report_html),
                "newmanJson": str(report_json),
                "failures": 0 if proc.returncode == 0 else 1,
            },
        )


class MongoVerifyPlugin:
    type = "mongo.verify"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        try:
            from pymongo import MongoClient  # type: ignore
        except Exception as err:  # noqa: BLE001
            raise StepExecutionError("mongo.verify requires pymongo installed") from err

        uri = step_with.get("uri") or ctx["env"].get("MONGO_URI")
        db_name = step_with.get("db")
        if not isinstance(uri, str) or not uri.strip():
            raise StepExecutionError("mongo.verify requires with.uri or MONGO_URI")
        if not isinstance(db_name, str) or not db_name.strip():
            raise StepExecutionError("mongo.verify requires with.db")

        client = MongoClient(uri)
        db = client[db_name]
        results = []
        for query in step_with.get("queries", []):
            collection = db[query["collection"]]
            docs = list(collection.find(query.get("filter", {})).limit(int(query.get("limit", 50))))
            serializable_docs = json.loads(json.dumps(docs, default=str))
            results.append(
                {
                    "name": query["name"],
                    "count": len(serializable_docs),
                    "sample": serializable_docs[: int(query.get("sample", 3))],
                }
            )

        assertions = []
        for assertion in step_with.get("assert", []):
            query_name = assertion.get("query")
            actual = next((item["count"] for item in results if item["name"] == query_name), 0)
            op = assertion.get("op")
            expected = int(assertion.get("value", 0))
            ok = (op == "gte" and actual >= expected) or (op == "lte" and actual <= expected) or (op == "eq" and actual == expected)
            assertions.append({**assertion, "actual": actual, "ok": ok})

        step_dir = ctx["step_dir"](step_index, step_name)
        queries_path = ctx["write_json"](step_dir, "queries.json", step_with.get("queries", []))
        results_path = ctx["write_json"](step_dir, "results.json", results)
        assertions_path = ctx["write_json"](step_dir, "assertions.json", assertions)
        client.close()

        return StepResult(
            ok=all(item["ok"] for item in assertions),
            details={"assertions": assertions},
            evidence_paths=[queries_path, results_path, assertions_path],
            exports={
                "mongoOk": all(item["ok"] for item in assertions),
                "assertFailed": sum(1 for item in assertions if not item["ok"]),
            },
        )


class JiraPluginBase:
    def _request(self, method: str, path: str, *, payload: Any, cfg: dict[str, Any], ctx: dict[str, Any]) -> Any:
        base = cfg.get("baseUrl") or ctx["env"].get("JIRA_BASE_URL")
        email = cfg.get("email") or ctx["env"].get("JIRA_EMAIL")
        token = cfg.get("apiToken") or ctx["env"].get("JIRA_API_TOKEN")
        if not all([base, email, token]):
            raise StepExecutionError("Missing Jira config (JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN)")

        full_url = f"{str(base).rstrip('/')}{path}"
        auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            full_url,
            method=method,
            data=data,
            headers={
                "Authorization": f"Basic {auth}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            raise StepExecutionError(f"Jira API request failed ({err.code}): {body}") from err


class JiraFetchPlugin(JiraPluginBase):
    type = "jira.fetch"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        issue_key = step_with.get("issueKey") or ctx["vars"].get("issueKey")
        if not isinstance(issue_key, str) or not issue_key.strip():
            raise StepExecutionError("jira.fetch requires issueKey")

        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}", payload=None, cfg=step_with, ctx=ctx)
        step_dir = ctx["step_dir"](step_index, step_name)
        issue_path = ctx["write_json"](step_dir, "issue.json", payload)
        return StepResult(
            ok=True,
            details={"issueKey": issue_key},
            evidence_paths=[issue_path],
            exports={"jiraIssueId": payload.get("id"), "jiraKey": payload.get("key", issue_key)},
        )


class JiraCommentPlugin(JiraPluginBase):
    type = "jira.comment"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        issue_key = step_with.get("issueKey") or ctx["vars"].get("issueKey")
        if not isinstance(issue_key, str) or not issue_key.strip():
            raise StepExecutionError("jira.comment requires issueKey")
        body = str(step_with.get("body") or f"Run {ctx['run_id']} completed. See attached evidence.")

        payload = self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            payload={"body": body},
            cfg=step_with,
            ctx=ctx,
        )
        step_dir = ctx["step_dir"](step_index, step_name)
        comment_path = ctx["write_json"](step_dir, "comment.json", payload)
        return StepResult(
            ok=True,
            details={"issueKey": issue_key},
            evidence_paths=[comment_path],
            exports={"jiraCommentId": payload.get("id")},
        )


class JiraAttachPlugin(JiraPluginBase):
    type = "jira.attach"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        issue_key = step_with.get("issueKey") or ctx["vars"].get("issueKey")
        files = list(step_with.get("files", []))
        if not isinstance(issue_key, str) or not issue_key.strip():
            raise StepExecutionError("jira.attach requires issueKey")
        if not files:
            raise StepExecutionError("jira.attach requires with.files")

        # Cloud Jira requires multipart form-data; use curl for portability.
        base = step_with.get("baseUrl") or ctx["env"].get("JIRA_BASE_URL")
        email = step_with.get("email") or ctx["env"].get("JIRA_EMAIL")
        token = step_with.get("apiToken") or ctx["env"].get("JIRA_API_TOKEN")
        if not all([base, email, token]):
            raise StepExecutionError("Missing Jira config (JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN)")

        command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "-u",
            f"{email}:{token}",
            "-H",
            "X-Atlassian-Token: no-check",
            f"{str(base).rstrip('/')}/rest/api/3/issue/{issue_key}/attachments",
        ]
        for file_path in files:
            command.extend(["-F", f"file=@{file_path}"])

        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise StepExecutionError(f"jira.attach failed: {proc.stderr.strip()}")

        payload = json.loads(proc.stdout) if proc.stdout.strip() else []
        step_dir = ctx["step_dir"](step_index, step_name)
        attachments_path = ctx["write_json"](step_dir, "attachments.json", payload)
        return StepResult(
            ok=True,
            details={"issueKey": issue_key, "files": files},
            evidence_paths=[attachments_path],
            exports={"jiraAttachmentIds": [item.get("id") for item in payload if isinstance(item, dict)]},
        )


class LegacyPlugin:
    def __init__(self, type_name: str):
        self.type = type_name

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        step_dir = ctx["step_dir"](step_index, step_name)
        out = {"legacy": True, "type": self.type, "input": step_with}
        path = ctx["write_json"](step_dir, "legacy.json", out)
        return StepResult(ok=True, details=out, evidence_paths=[path])


class PluginRegistry:
    def __init__(self, plugins: list[Plugin] | None = None):
        initial_plugins = plugins or [
            AppLauncherStartPlugin(),
            AppLauncherStopPlugin(),
            HttpHealthPlugin(),
            PostmanRunPlugin(),
            MongoVerifyPlugin(),
            JiraFetchPlugin(),
            JiraCommentPlugin(),
            JiraAttachPlugin(),
        ]
        self._plugins = {plugin.type: plugin for plugin in initial_plugins}

    def resolve(self, type_name: str) -> Plugin:
        plugin = self._plugins.get(type_name)
        if plugin is None and type_name.startswith("legacy."):
            return LegacyPlugin(type_name)
        if plugin is None:
            raise PluginResolutionError(f"No plugin registered for '{type_name}'")
        return plugin

    def available_plugin_names(self) -> set[str]:
        return set(self._plugins.keys())
