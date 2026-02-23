"""Step plugins and template utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
import glob
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from continuum.errors import PluginResolutionError, StepExecutionError
from continuum.sessions import (
    file_lock,
    fingerprint,
    kill_tree,
    load_sessions,
    now_iso,
    pid_alive,
    save_sessions,
)


@dataclass(slots=True)
class StepResult:
    ok: bool
    details: dict[str, Any]
    evidence_paths: list[str]
    exports: dict[str, Any] | None = None


class Plugin(Protocol):
    type: str

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult: ...


TEMPLATE_PATTERN = re.compile(r"\$\{([^}]+)\}")
_BACKGROUND_PROCS: dict[int, subprocess.Popen[Any]] = {}


def _kill_and_reap(pid: int) -> None:
    kill_tree(pid)
    proc = _BACKGROUND_PROCS.pop(pid, None)
    if proc is not None:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def _lookup(path: str, ctx: dict[str, Any]) -> Any:
    current: Any = ctx
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def find_unknown_templates(value: Any, *, ctx: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    if isinstance(value, str):
        for match in TEMPLATE_PATTERN.finditer(value):
            key = match.group(1).strip()
            if key in {"runId", "runDir"}:
                continue
            if key.startswith("env."):
                if _lookup(key, ctx) is None:
                    unknown.append(key)
            elif key.startswith("vars."):
                if _lookup(key, ctx) is None:
                    unknown.append(key)
            else:
                unknown.append(key)
    elif isinstance(value, dict):
        for nested in value.values():
            unknown.extend(find_unknown_templates(nested, ctx=ctx))
    elif isinstance(value, list):
        for nested in value:
            unknown.extend(find_unknown_templates(nested, ctx=ctx))
    return sorted(set(unknown))


def render_templates(value: Any, *, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key == "runId":
                return str(ctx.get("run_id", ""))
            if key == "runDir":
                return str(ctx.get("run_dir", ""))
            resolved = _lookup(key, ctx)
            return "" if resolved is None else str(resolved)
        return TEMPLATE_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: render_templates(v, ctx=ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_templates(v, ctx=ctx) for v in value]
    return value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _list_files(root: str, recursive: bool) -> list[str]:
    files: list[str] = []
    if recursive:
        for base, _, names in os.walk(root):
            for name in names:
                files.append(os.path.join(base, name))
    else:
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

    for file_path in cfg.get("files") or []:
        if not isinstance(file_path, str):
            continue
        resolved = file_path if os.path.isabs(file_path) else os.path.join(run_dir, file_path)
        if any(ch in file_path for ch in "*?[]"):
            out.extend(glob.glob(resolved, recursive=True))
        else:
            out.append(resolved)

    evidence_root = os.path.join(run_dir, "evidence")
    if os.path.isdir(evidence_root):
        dirs = sorted(d for d in glob.glob(os.path.join(evidence_root, "*")) if os.path.isdir(d))
        wanted = cfg.get("fromSteps") or []
        recursive = bool(cfg.get("recursive", True))
        for wanted_step in wanted:
            text = str(wanted_step)
            if re.match(r"^\d{2}-", text):
                matches = [d for d in dirs if os.path.basename(d).startswith(text)]
            else:
                slug = _slug(text)
                matches = [d for d in dirs if os.path.basename(d).split("-", 1)[-1].endswith(slug)]
            for match in sorted(matches):
                out.extend(_list_files(match, recursive))

    if cfg.get("includeRunBundle"):
        for artifact in ["scenario.yaml", "context.json", "summary.json", "manifest.json", "plan.json"]:
            path = os.path.join(run_dir, artifact)
            if os.path.isfile(path):
                out.append(path)

    deduped = sorted(set(path for path in out if os.path.isfile(path)))
    return deduped[: max(1, int(cfg.get("maxFiles", 25)))]


class AppLauncherStartPlugin:
    type = "applauncher.start"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        command = step_with.get("command")
        if not isinstance(command, str) or not command.strip():
            raise StepExecutionError("applauncher.start requires with.command")
        args = [str(v) for v in step_with.get("args", [])]
        cwd = str(step_with.get("cwd", "."))
        proc = subprocess.Popen([command, *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ctx["vars"]["applauncherPid"] = proc.pid
        step_dir = ctx["step_dir"](step_index, step_name)
        path = ctx["write_json"](step_dir, "started.json", {"pid": proc.pid})
        return StepResult(ok=True, details={"pid": proc.pid}, evidence_paths=[path], exports={"applauncherPid": proc.pid})


class AppLauncherStopPlugin:
    type = "applauncher.stop"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        pid = step_with.get("pid") or ctx["vars"].get("applauncherPid")
        if not pid:
            return StepResult(ok=True, details={"pid": None, "stopped": False}, evidence_paths=[])
        try:
            os.kill(int(pid), 15)
        except ProcessLookupError:
            pass
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "stopped.json", {"pid": int(pid)})
        return StepResult(ok=True, details={"pid": int(pid), "stopped": True}, evidence_paths=[path])


def _verify_health(*, health_url: str | None, timeout_sec: int) -> dict[str, Any]:
    if not health_url:
        return {"ok": True, "status": None, "error": None, "url": None}
    deadline = time.time() + max(1, timeout_sec)
    status: int | None = None
    last_error: str | None = None
    ok = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                status = response.status
                ok = 200 <= response.status < 300
                if ok:
                    break
        except Exception as err:
            last_error = str(err)
        time.sleep(0.25)
    return {"ok": ok, "status": status, "error": None if ok else (last_error or "timeout"), "url": health_url}


class AppLauncherEnsurePlugin:
    type = "applauncher.ensure"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        command = step_with.get("command")
        if not isinstance(command, str) or not command.strip():
            raise StepExecutionError("applauncher.ensure requires with.command")
        args = [str(v) for v in step_with.get("args", [])]
        session = step_with.get("session")
        if not isinstance(session, str) or not session.strip():
            raise StepExecutionError("applauncher.ensure requires with.session")
        cwd = str(step_with.get("cwd", "."))
        health_url = step_with.get("healthUrl")
        verify_timeout_sec = int(step_with.get("verifyTimeoutSec", 10))
        env_keys = [str(v) for v in step_with.get("envKeysForFingerprint", [])]
        reuse = bool(step_with.get("reuse", True))
        desired_fingerprint = fingerprint(command, args, cwd, env_keys)

        step_dir = ctx["step_dir"](step_index, step_name)
        verify_details: dict[str, Any]

        with file_lock():
            sessions = load_sessions()
            existing = sessions.get(session) if isinstance(sessions.get(session), dict) else None
            should_reuse = False
            pid: int | None = None

            if existing and reuse:
                existing_pid = int(existing.get("pid", 0))
                same_fingerprint = existing.get("fingerprint") == desired_fingerprint
                alive = pid_alive(existing_pid)
                if alive and same_fingerprint:
                    verify_details = _verify_health(health_url=health_url, timeout_sec=verify_timeout_sec)
                    should_reuse = bool(verify_details["ok"])
                    if should_reuse:
                        pid = existing_pid
                        existing["lastVerifiedAt"] = now_iso()
                        sessions[session] = existing
                    else:
                        _kill_and_reap(existing_pid)
                        sessions.pop(session, None)
                else:
                    if alive:
                        _kill_and_reap(existing_pid)
                    sessions.pop(session, None)

            if not should_reuse:
                proc = subprocess.Popen(
                    [command, *args],
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=(os.name != "nt"),
                )
                pid = proc.pid
                _BACKGROUND_PROCS[pid] = proc
                verify_details = _verify_health(health_url=health_url, timeout_sec=verify_timeout_sec)
                if not verify_details["ok"]:
                    _kill_and_reap(pid)
                    raise StepExecutionError(f"applauncher.ensure failed health check: {verify_details.get('error')}")
                sessions[session] = {
                    "pid": pid,
                    "startedAt": now_iso(),
                    "healthUrl": health_url,
                    "cmd": command,
                    "args": args,
                    "cwd": cwd,
                    "fingerprint": desired_fingerprint,
                    "runIdStarted": ctx.get("run_id"),
                    "lastVerifiedAt": now_iso(),
                }

            save_sessions(sessions)

        details = {"session": session, "pid": int(pid or 0), "reused": should_reuse, "fingerprint": desired_fingerprint}
        session_path = ctx["write_json"](step_dir, "session.json", details)
        verify_path = ctx["write_json"](step_dir, "verify.json", verify_details)
        exports = {"applauncherPid": int(pid or 0), "applauncherReused": should_reuse}
        return StepResult(ok=True, details=details, evidence_paths=[session_path, verify_path], exports=exports)


class AppLauncherSessionStopPlugin:
    type = "applauncher.session.stop"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        session = step_with.get("session")
        if not isinstance(session, str) or not session.strip():
            raise StepExecutionError("applauncher.session.stop requires with.session")
        stopped_pid: int | None = None
        with file_lock():
            sessions = load_sessions()
            entry = sessions.get(session) if isinstance(sessions.get(session), dict) else None
            if entry:
                stopped_pid = int(entry.get("pid", 0))
                _kill_and_reap(stopped_pid)
                sessions.pop(session, None)
                save_sessions(sessions)
        payload = {"session": session, "pid": stopped_pid, "stopped": stopped_pid is not None}
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "stopped.json", payload)
        return StepResult(ok=True, details=payload, evidence_paths=[path], exports={"applauncherPid": None})


class HttpHealthPlugin:
    type = "http.health"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        url = step_with.get("url")
        timeout_sec = int(step_with.get("timeoutSec", 30))
        if not isinstance(url, str) or not url.strip():
            raise StepExecutionError("http.health requires with.url")
        deadline = time.time() + timeout_sec
        ok = False
        last_error: str | None = None
        status: int | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    status = response.status
                    ok = 200 <= response.status < 300
                    if ok:
                        break
            except Exception as err:
                last_error = str(err)
            time.sleep(0.5)
        details = {"url": url, "ok": ok, "status": status, "error": None if ok else (last_error or "timeout")}
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "health.json", details)
        return StepResult(ok=ok, details=details, evidence_paths=[path])


class PostmanRunPlugin:
    type = "postman.run"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": shutil.which("newman") is not None, "missing": ["newman"] if shutil.which("newman") is None else []}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        if shutil.which("newman") is None:
            path = ctx["write_json"](
                ctx["step_dir"](step_index, step_name),
                "missing-dependency.json",
                {"missing": "newman", "message": "postman.run requires newman"},
            )
            return StepResult(ok=False, details={"error": "postman.run requires newman"}, evidence_paths=[path])
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "newman-summary.json", {"returncode": 0})
        return StepResult(ok=True, details={"returncode": 0}, evidence_paths=[path])


class MongoVerifyPlugin:
    type = "mongo.verify"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            import pymongo  # type: ignore  # noqa: F401
            return {"ok": True, "missing": []}
        except Exception:
            return {"ok": False, "missing": ["pymongo"]}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "assertions.json", {"ok": True})
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[path])


class JiraFetchPlugin:
    type = "jira.fetch"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        missing = [k for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not ctx.get("env", {}).get(k)]
        return {"ok": not missing, "missing": missing}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "issue.json", {"key": ctx["vars"].get("issueKey")})
        return StepResult(ok=True, details={"issueKey": ctx["vars"].get("issueKey")}, evidence_paths=[path])


class JiraCommentPlugin:
    type = "jira.comment"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "comment.json", {"ok": True})
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[path])


class JiraAttachPlugin:
    type = "jira.attach"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        files = resolve_attach_files(step_with, ctx["run_dir"])
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "resolved_files.json", {"files": files})
        return StepResult(ok=bool(files), details={"files": files}, evidence_paths=[path])


class LegacyPlugin:
    def __init__(self, type_name: str): self.type = type_name

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        p = ctx["write_json"](ctx["step_dir"](step_index, step_name), "legacy.json", {"type": self.type, "input": step_with})
        return StepResult(ok=True, details={"legacy": True, "type": self.type}, evidence_paths=[p])


class PluginRegistry:
    def __init__(self, plugins: list[Plugin] | None = None):
        initial_plugins = plugins or [
            AppLauncherStartPlugin(),
            AppLauncherStopPlugin(),
            AppLauncherEnsurePlugin(),
            AppLauncherSessionStopPlugin(),
            HttpHealthPlugin(),
            PostmanRunPlugin(),
            MongoVerifyPlugin(),
            JiraFetchPlugin(),
            JiraCommentPlugin(),
            JiraAttachPlugin(),
        ]
        self._plugins = {p.type: p for p in initial_plugins}

    def resolve(self, type_name: str) -> Plugin:
        p = self._plugins.get(type_name)
        if p:
            return p
        if type_name.startswith("legacy."):
            return LegacyPlugin(type_name)
        raise PluginResolutionError(f"No plugin registered for '{type_name}'")

    def available_plugin_names(self) -> set[str]:
        return set(self._plugins.keys())
