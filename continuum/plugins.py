"""Step plugins for deterministic scenario orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any
import base64
import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from continuum.errors import PluginResolutionError, StepExecutionError
from continuum.preflight import which


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
                var_key = key[5:]
                return str(ctx["vars"].get(var_key, ""))
            return str(ctx["vars"].get(key, ""))

        return pattern.sub(repl, value)

    if isinstance(value, dict):
        return {k: render_templates(v, ctx=ctx) for k, v in value.items()}

    if isinstance(value, list):
        return [render_templates(v, ctx=ctx) for v in value]

    return value


def _slug(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized


def _list_files(root: str, recursive: bool) -> list[str]:
    files: list[str] = []
    if recursive:
        for base, _, names in os.walk(root):
            for name in names:
                files.append(os.path.join(base, name))
        return files

    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            files.append(path)
    return files


def resolve_attach_files(cfg: dict[str, Any], run_dir: str) -> list[str]:
    out: list[str] = []

    for pattern in cfg.get("globs") or []:
        if not isinstance(pattern, str):
            continue
        resolved_pattern = pattern if os.path.isabs(pattern) else os.path.join(run_dir, pattern)
        out.extend(glob.glob(resolved_pattern, recursive=True))

    files = cfg.get("files") or []
    for file_path in files:
        rendered = str(file_path)
        if any(token in rendered for token in "*?[]"):
            resolved_pattern = rendered if os.path.isabs(rendered) else os.path.join(run_dir, rendered)
            out.extend(glob.glob(resolved_pattern, recursive=True))
        else:
            out.append(rendered if os.path.isabs(rendered) else os.path.join(run_dir, rendered))

    evidence_root = os.path.join(run_dir, "evidence")
    if os.path.isdir(evidence_root):
        dirs = [os.path.join(evidence_root, d) for d in os.listdir(evidence_root)]
        dirs = [d for d in dirs if os.path.isdir(d)]

        wanted = cfg.get("fromSteps") or []
        recursive = bool(cfg.get("recursive", True))

        for wanted_step in wanted:
            step_name = str(wanted_step)
            if re.match(r"^\d{2}\-", step_name):
                matches = [d for d in dirs if os.path.basename(d).startswith(step_name)]
            else:
                slug = _slug(step_name)
                matches = [d for d in dirs if os.path.basename(d).split("-", 1)[-1].endswith(slug)]

            for match in sorted(matches):
                out.extend(_list_files(match, recursive))

    if cfg.get("includeRunBundle"):
        for artifact in ["scenario.yaml", "context.json", "summary.json", "manifest.json"]:
            path = os.path.join(run_dir, artifact)
            if os.path.isfile(path):
                out.append(path)

    out = [path for path in out if os.path.isfile(path)]
    out = sorted(set(out))

    max_files = int(cfg.get("maxFiles", 25))
    return out[:max_files]


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

        step_dir = Path(ctx["step_dir"](step_index, step_name))
        step_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = step_dir / "stdout.log"
        stderr_path = step_dir / "stderr.log"
        stdout_handle = stdout_path.open("a", encoding="utf-8")
        stderr_handle = stderr_path.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [command, *[str(item) for item in args]],
                cwd=cwd,
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
        finally:
            stdout_handle.close()
            stderr_handle.close()

        ctx["vars"]["__applauncherPid"] = process.pid
        ctx["vars"]["__applauncherCwd"] = cwd

        out_log = str(stdout_path)
        err_log = str(stderr_path)
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
            step_dir = ctx["step_dir"](step_index, step_name)
            dependency_path = ctx["write_json"](
                step_dir,
                "missing-dependency.json",
                {
                    "missing": "newman",
                    "message": "postman.run requires newman installed and available on PATH",
                },
            )
            return StepResult(
                ok=False,
                details={"error": "postman.run requires newman installed and available on PATH"},
                evidence_paths=[dependency_path],
            )

        collection = step_with.get("collection")
        if not isinstance(collection, str) or not collection.strip():
            raise StepExecutionError("postman.run requires with.collection")

        step_dir = Path(step_dir)
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
        step_dir = ctx["step_dir"](step_index, step_name)
        try:
            from pymongo import MongoClient  # type: ignore
        except Exception:
            preflight_path = ctx["write_json"](
                step_dir,
                "preflight.json",
                {
                    "ok": False,
                    "missing": ["pymongo"],
                    "hint": "pip install pymongo",
                },
            )
            return StepResult(
                ok=False,
                details={"error": "Missing dependency: pymongo"},
                evidence_paths=[preflight_path],
            )

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
    def _missing_cfg_env(self, cfg: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
        required = []
        if not cfg.get("baseUrl") and not ctx["env"].get("JIRA_BASE_URL"):
            required.append("JIRA_BASE_URL")
        if not cfg.get("email") and not ctx["env"].get("JIRA_EMAIL"):
            required.append("JIRA_EMAIL")
        if not cfg.get("apiToken") and not ctx["env"].get("JIRA_API_TOKEN"):
            required.append("JIRA_API_TOKEN")
        return required

    def _preflight_cfg(self, step_dir: str, cfg: dict[str, Any], ctx: dict[str, Any]) -> StepResult | None:
        required = self._missing_cfg_env(cfg, ctx)
        if not required:
            return None
        preflight_path = ctx["write_json"](
            step_dir,
            "preflight.json",
            {
                "ok": False,
                "missingEnv": required,
                "hint": "Set env vars or pass baseUrl/email/apiToken in step.with",
            },
        )
        return StepResult(
            ok=False,
            details={"error": f"Missing Jira config: {', '.join(required)}"},
            evidence_paths=[preflight_path],
        )

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
        step_dir = ctx["step_dir"](step_index, step_name)
        preflight_result = self._preflight_cfg(step_dir, step_with, ctx)
        if preflight_result:
            return preflight_result

        issue_key = step_with.get("issueKey") or ctx["vars"].get("issueKey")
        if not isinstance(issue_key, str) or not issue_key.strip():
            raise StepExecutionError("jira.fetch requires issueKey")

        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}", payload=None, cfg=step_with, ctx=ctx)
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
        step_dir = ctx["step_dir"](step_index, step_name)
        preflight_result = self._preflight_cfg(step_dir, step_with, ctx)
        if preflight_result:
            return preflight_result

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
        step_dir = ctx["step_dir"](step_index, step_name)
        preflight_result = self._preflight_cfg(step_dir, step_with, ctx)
        if preflight_result:
            return preflight_result

        issue_key = step_with.get("issueKey") or ctx["vars"].get("issueKey")
        if not isinstance(issue_key, str) or not issue_key.strip():
            raise StepExecutionError("jira.attach requires issueKey")

        has_sources = any(step_with.get(key) for key in ["files", "globs", "fromSteps"]) or bool(
            step_with.get("includeRunBundle")
        )
        if not has_sources:
            raise StepExecutionError("jira.attach requires one of with.files, with.globs, with.fromSteps, includeRunBundle")

        step_dir = ctx["step_dir"](step_index, step_name)
        resolved_files = resolve_attach_files(step_with, ctx["run_dir"])
        resolved_path = ctx["write_json"](step_dir, "resolved_files.json", {"files": resolved_files})

        if not resolved_files:
            return StepResult(
                ok=False,
                details={"error": "No files resolved to attach"},
                evidence_paths=[resolved_path],
            )

        # Cloud Jira requires multipart form-data; use curl for portability.
        base = step_with.get("baseUrl") or ctx["env"].get("JIRA_BASE_URL")
        email = step_with.get("email") or ctx["env"].get("JIRA_EMAIL")
        token = step_with.get("apiToken") or ctx["env"].get("JIRA_API_TOKEN")

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
        for file_path in resolved_files:
            command.extend(["-F", f"file=@{file_path}"])

        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise StepExecutionError(f"jira.attach failed: {proc.stderr.strip()}")

        payload = json.loads(proc.stdout) if proc.stdout.strip() else []
        attachments_path = ctx["write_json"](step_dir, "attachments.json", payload)
        return StepResult(
            ok=True,
            details={"issueKey": issue_key, "files": resolved_files},
            evidence_paths=[resolved_path, attachments_path],
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
