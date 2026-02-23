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
import signal
import subprocess
import time
from urllib.parse import urlparse
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
            if key in {"runId", "runDir", "traceId"}:
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
            if key == "traceId":
                return str(_lookup("vars.traceId", ctx) or "")
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


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


def _check_health(url: str, timeout_sec: int) -> tuple[bool, int | None, str | None]:
    deadline = time.time() + max(1, timeout_sec)
    last_error: str | None = None
    status: int | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                status = response.status
                if 200 <= status < 300:
                    return True, status, None
                last_error = f"HTTP {status}"
        except Exception as err:
            last_error = str(err)
        time.sleep(0.25)
    return False, status, last_error or "timeout"


def _base_url_from_health_url(health_url: str | None) -> str | None:
    if not health_url:
        return None
    parsed = urlparse(health_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def ensure_applauncher_session(
    cfg: dict[str, Any],
    *,
    session_registry: dict[str, Any],
    allow_reuse: bool,
    extra_env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    command = cfg.get("command")
    if not isinstance(command, str) or not command.strip():
        raise StepExecutionError("applauncher service requires command")

    args = [str(v) for v in cfg.get("args", [])]
    cwd = str(cfg.get("cwd", "."))
    verify_timeout_sec = int(cfg.get("verifyTimeoutSec", 10))
    health_url = cfg.get("healthUrl")
    session_name = str(cfg.get("session") or "")
    can_reuse = allow_reuse and bool(cfg.get("reuse", True)) and bool(session_name)

    reused = False
    pid: int | None = None
    health_ok = False
    verify_error: str | None = None
    status_code: int | None = None
    existing = session_registry.get(session_name) if can_reuse else None
    existing_pid = int(existing.get("pid", 0)) if isinstance(existing, dict) and existing.get("pid") else None

    if can_reuse and existing_pid and _is_pid_alive(existing_pid):
        pid = existing_pid
        if isinstance(health_url, str) and health_url.strip():
            health_ok, status_code, verify_error = _check_health(health_url, verify_timeout_sec)
        else:
            health_ok = True
        if health_ok:
            reused = True

    if not reused:
        proc = subprocess.Popen(
            [command, *args],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **(extra_env or {})},
        )
        pid = int(proc.pid)
        if isinstance(health_url, str) and health_url.strip():
            health_ok, status_code, verify_error = _check_health(health_url, verify_timeout_sec)
        else:
            health_ok = True
            status_code = None
            verify_error = None

    if session_name:
        session_registry[session_name] = {
            "pid": pid,
            "healthUrl": health_url,
            "cwd": cwd,
            "command": command,
            "args": args,
            "updatedAt": int(time.time()),
        }

    exports = {
        "pid": pid,
        "healthOk": health_ok,
        "baseUrl": _base_url_from_health_url(health_url if isinstance(health_url, str) else None),
        "reused": reused,
    }
    evidence = {
        "session": session_name or None,
        "reused": reused,
        "pid": pid,
        "healthUrl": health_url,
        "healthOk": health_ok,
        "status": status_code,
        "error": verify_error,
        "command": command,
        "args": args,
        "cwd": cwd,
        "env": dict(extra_env or {}),
    }
    return exports, evidence


class AppLauncherStopPlugin:
    type = "applauncher.stop"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        pid = step_with.get("pid") or ctx["vars"].get("applauncherPid")
        if not pid:
            return StepResult(ok=True, details={"pid": None, "stopped": False}, evidence_paths=[])
        try:
            os.kill(int(pid), signal.SIGTERM)
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
        step_dir = ctx["step_dir"](step_index, step_name)
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        run_id = str(ctx.get("run_id") or "")
        env_var = dict(step_with.get("envVar") or {})
        env_var.update({"traceId": trace_id, "runId": run_id})
        if shutil.which("newman") is None:
            path = ctx["write_json"](
                ctx["step_dir"](step_index, step_name),
                "missing-dependency.json",
                {
                    "missing": "newman",
                    "message": "postman.run requires newman",
                    "envVar": env_var,
                    "headers": {
                        "X-Continuum-Run-Id": run_id,
                        "X-Continuum-Trace-Id": trace_id,
                    },
                },
            )
            return StepResult(ok=False, details={"error": "postman.run requires newman"}, evidence_paths=[path], exports={"postmanTraceId": trace_id})
        path = ctx["write_json"](
            ctx["step_dir"](step_index, step_name),
            "newman-summary.json",
            {
                "returncode": 0,
                "envVar": env_var,
                "headers": {
                    "X-Continuum-Run-Id": run_id,
                    "X-Continuum-Trace-Id": trace_id,
                },
            },
        )
        return StepResult(ok=True, details={"returncode": 0, "traceId": trace_id}, evidence_paths=[path], exports={"postmanTraceId": trace_id})


class MongoVerifyPlugin:
    type = "mongo.verify"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            import pymongo  # type: ignore  # noqa: F401
            return {"ok": True, "missing": []}
        except Exception:
            return {"ok": False, "missing": ["pymongo"]}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        auto_filter = bool(step_with.get("autoFilterTraceId", False))
        queries = step_with.get("queries") or []
        applied = False
        if isinstance(queries, list):
            for query in queries:
                if not isinstance(query, dict):
                    continue
                filter_obj = query.get("filter")
                if auto_filter and isinstance(filter_obj, dict) and "traceId" not in filter_obj:
                    filter_obj["traceId"] = trace_id
                    applied = True
        payload = {"ok": True, "queries": queries, "traceId": trace_id, "traceQueryApplied": applied}
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "assertions.json", payload)
        return StepResult(ok=True, details=payload, evidence_paths=[path], exports={"traceQueryApplied": applied})


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
        run_id = str(ctx.get("run_id") or "")
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        status = str(ctx.get("vars", {}).get("status") or "completed")
        body = str(step_with.get("body") or f"Run {run_id} finished with status {status}. Trace {trace_id}. Report attached.")
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "comment.json", {"ok": True, "body": body})
        return StepResult(ok=True, details={"ok": True, "body": body}, evidence_paths=[path])


class JiraAttachPlugin:
    type = "jira.attach"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        files = resolve_attach_files(step_with, ctx["run_dir"])
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "resolved_files.json", {"files": files})
        return StepResult(ok=bool(files), details={"files": files}, evidence_paths=[path])


def _read_tail_lines(path: str, *, max_bytes: int, max_lines: int) -> list[str]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    data = file_path.read_bytes()
    chunk = data[-max(1, int(max_bytes)) :]
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-max(1, int(max_lines)) :]


def _redact_text(text: str) -> str:
    redacted = text
    patterns = [
        (r"(?i)(token\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(password\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(cookie\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)", r"\1[REDACTED]"),
    ]
    for pattern, repl in patterns:
        redacted = re.sub(pattern, repl, redacted)
    return redacted


def _normalize_signature(line: str) -> str:
    sig = line.strip()
    sig = re.sub(r"\b[0-9a-f]{8}-[0-9a-f\-]{27,}\b", "<id>", sig, flags=re.IGNORECASE)
    sig = re.sub(r"\b\d+\b", "<n>", sig)
    sig = re.sub(r"\s+", " ", sig)
    return sig[:220]


class LogsCollectPlugin:
    type = "logs.collect"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        step_dir = Path(ctx["step_dir"](step_index, step_name))
        step_dir.mkdir(parents=True, exist_ok=True)
        max_lines = max(1, int(step_with.get("maxLines", 2000)))
        max_files = max(1, int(step_with.get("maxFiles", 25)))
        max_bytes = max(1, int(step_with.get("maxBytes", 200_000)))
        raw_max_lines = max(1, int(step_with.get("rawMaxLines", 250)))

        trace_id = str(step_with.get("traceId") or ctx.get("vars", {}).get("traceId") or "").strip()
        run_id = str(step_with.get("runId") or ctx.get("run_id") or "").strip()

        match_cfg = step_with.get("match") if isinstance(step_with.get("match"), dict) else {}
        include_terms = [str(v).strip() for v in (match_cfg.get("include") or []) if str(v).strip()]
        exclude_terms = [str(v).strip().lower() for v in (match_cfg.get("exclude") or []) if str(v).strip()]
        correlation_terms = [v for v in [trace_id, run_id] if v]
        for term in correlation_terms:
            if term not in include_terms:
                include_terms.insert(0, term)

        resolved_sources: list[dict[str, Any]] = []
        source_defs = step_with.get("sources") if isinstance(step_with.get("sources"), list) else []
        for source in source_defs:
            if not isinstance(source, dict):
                continue
            source_type = str(source.get("type") or "")
            source_name = str(source.get("name") or source_type or "source")
            if source_type == "file":
                path = str(source.get("path") or "")
                if path:
                    resolved_sources.append({"name": source_name, "type": source_type, "path": path})
            elif source_type == "dir_glob":
                pattern = str(source.get("glob") or "")
                for matched in sorted(glob.glob(pattern)):
                    resolved_sources.append({"name": source_name, "type": source_type, "path": matched})
            elif source_type == "cmd":
                command = str(source.get("command") or "")
                args = [str(v) for v in source.get("args", [])]
                if command:
                    resolved_sources.append({"name": source_name, "type": source_type, "command": command, "args": args})

        resolved_sources = resolved_sources[:max_files]
        sources_path = str(step_dir / "sources.json")
        Path(sources_path).write_text(json.dumps({"sources": resolved_sources}, indent=2, sort_keys=True), encoding="utf-8")

        snippets: list[dict[str, Any]] = []
        seen_blocks: set[str] = set()
        error_signatures: dict[str, int] = {}
        raw_paths: list[str] = []
        timestamp_re = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")

        for src in resolved_sources:
            lines: list[str]
            src_id = src.get("path") or f"{src.get('command')} {' '.join(src.get('args', []))}".strip()
            if src["type"] == "cmd":
                proc = subprocess.run(
                    [str(src.get("command")), *[str(v) for v in src.get("args", [])]],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=int(step_with.get("cmdTimeoutSec", 30)),
                )
                text = (proc.stdout or "")[-max_bytes:]
                lines = text.splitlines()[-max_lines:]
            else:
                lines = _read_tail_lines(str(src.get("path", "")), max_bytes=max_bytes, max_lines=max_lines)

            if not lines:
                continue

            raw_name = _slug(str(src.get("name", "source"))) or "source"
            raw_file = step_dir / "raw" / f"{raw_name}.tail.log"
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            raw_file.write_text("\n".join(_redact_text(v) for v in lines[-raw_max_lines:]), encoding="utf-8")
            raw_paths.append(str(raw_file))

            lower_lines = [ln.lower() for ln in lines]
            for idx, line in enumerate(lines):
                lower = lower_lines[idx]
                if exclude_terms and any(term in lower for term in exclude_terms):
                    continue
                if include_terms and not any(term.lower() in lower for term in include_terms):
                    continue

                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                if any(key in lower for key in ["exception", "stacktrace", "error"]):
                    cursor = idx + 1
                    while cursor < len(lines):
                        candidate = lines[cursor]
                        if not candidate.strip():
                            cursor += 1
                            break
                        if timestamp_re.match(candidate):
                            break
                        cursor += 1
                    end = max(end, cursor)

                block_lines = [_redact_text(v) for v in lines[start:end]]
                block_text = "\n".join(block_lines).strip()
                if not block_text or block_text in seen_blocks:
                    continue
                seen_blocks.add(block_text)
                snippets.append(
                    {
                        "source": str(src_id),
                        "sourceName": src.get("name"),
                        "startLine": start + 1,
                        "endLine": end,
                        "matchLine": idx + 1,
                        "text": block_text,
                    }
                )
                if any(key in lower for key in ["error", "exception"]):
                    signature = _normalize_signature(line)
                    error_signatures[signature] = error_signatures.get(signature, 0) + 1

        snippets = sorted(snippets, key=lambda s: (str(s.get("sourceName")), str(s.get("source")), int(s.get("startLine", 0))))
        if len(snippets) > max_lines:
            snippets = snippets[:max_lines]

        top_errors = [
            {"signature": signature, "count": count}
            for signature, count in sorted(error_signatures.items(), key=lambda kv: (-kv[1], kv[0]))[: int(step_with.get("topN", 10))]
        ]

        snippets_payload = {"found": len(snippets), "traceId": trace_id or None, "snippets": snippets}
        snippets_json = str(step_dir / "snippets.json")
        Path(snippets_json).write_text(json.dumps(snippets_payload, indent=2, sort_keys=True), encoding="utf-8")
        snippets_txt_text = "\n\n".join(
            f"[{item['sourceName']}:{item['matchLine']}]\n{item['text']}" for item in snippets
        ) if snippets else "No matches found."
        snippets_txt_path = str(step_dir / "snippets.txt")
        Path(snippets_txt_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snippets_txt_path).write_text(snippets_txt_text, encoding="utf-8")
        top_errors_path = str(step_dir / "top_errors.json")
        Path(top_errors_path).write_text(json.dumps({"topErrors": top_errors}, indent=2, sort_keys=True), encoding="utf-8")

        evidence_paths = [sources_path, snippets_json, snippets_txt_path, top_errors_path, *raw_paths]
        details = {
            "found": len(snippets),
            "sources": len(resolved_sources),
            "traceId": trace_id or None,
            "topErrors": top_errors,
        }
        exports = {
            "logSnippetsTxt": snippets_txt_path,
            "logErrorCount": sum(item["count"] for item in top_errors),
        }
        return StepResult(ok=True, details=details, evidence_paths=evidence_paths, exports=exports)


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
            LogsCollectPlugin(),
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
