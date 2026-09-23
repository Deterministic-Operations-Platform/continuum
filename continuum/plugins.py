"""Step plugins and template utilities."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
import glob
import json
import mimetypes
import os
import re
import socket
import sqlite3
import shutil
import signal
import subprocess
import time
from urllib.parse import quote, urlencode, urlparse
import urllib.error
import urllib.request
import uuid

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


def resolve_newman_executable() -> str | None:
    candidates = ["newman"]
    local_candidates: list[Path]
    if os.name == "nt":
        # On Windows, subprocess([...], shell=False) cannot reliably execute
        # extensionless command names from PATH; prefer explicit script/binary.
        candidates = ["newman.cmd", "newman.exe", "newman.bat", "newman"]
        local_candidates = [
            Path.cwd() / ".continuum" / "vendor" / "npm" / "node_modules" / ".bin" / "newman.cmd",
            Path.cwd() / "node_modules" / ".bin" / "newman.cmd",
        ]
    else:
        local_candidates = [
            Path.cwd() / ".continuum" / "vendor" / "npm" / "node_modules" / ".bin" / "newman",
            Path.cwd() / "node_modules" / ".bin" / "newman",
        ]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    for candidate in local_candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_command(command: str) -> str | None:
    candidate = str(command or "").strip()
    if not candidate:
        return None
    if candidate.lower() == "newman":
        return resolve_newman_executable()
    return shutil.which(candidate)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _connector_live_gate_enabled(*, ctx: dict[str, Any], connector: str) -> bool:
    env = ctx.get("env", {}) if isinstance(ctx.get("env"), dict) else {}
    connector_key = f"CONTINUUM_ENABLE_LIVE_{connector.upper()}"
    return _is_truthy(env.get("CONTINUUM_ENABLE_LIVE_CONNECTORS")) or _is_truthy(env.get(connector_key))


def _live_mode_requested(step_with: dict[str, Any]) -> bool:
    return _is_truthy(step_with.get("live", False))


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _jira_config(step_with: dict[str, Any], ctx: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    env = ctx.get("env", {}) if isinstance(ctx.get("env"), dict) else {}
    base_url = str(step_with.get("baseUrl") or env.get("JIRA_BASE_URL") or "").strip().rstrip("/")
    email = str(step_with.get("email") or env.get("JIRA_EMAIL") or "").strip()
    token = str(step_with.get("apiToken") or env.get("JIRA_API_TOKEN") or "").strip()
    timeout_sec = max(1, int(step_with.get("timeoutSec", 30)))
    missing: list[str] = []
    if not base_url:
        missing.append("JIRA_BASE_URL")
    if not email:
        missing.append("JIRA_EMAIL")
    if not token:
        missing.append("JIRA_API_TOKEN")
    return {"baseUrl": base_url, "email": email, "token": token, "timeoutSec": timeout_sec}, missing


def _jira_preflight(
    *,
    step_with: dict[str, Any],
    ctx: dict[str, Any],
    require_issue_key: bool,
) -> dict[str, Any]:
    requested_live = _live_mode_requested(step_with)
    if not requested_live:
        return {"ok": True, "missing": [], "mode": "stub"}

    missing: list[str] = []
    if not _connector_live_gate_enabled(ctx=ctx, connector="jira"):
        missing.append("CONTINUUM_ENABLE_LIVE_CONNECTORS or CONTINUUM_ENABLE_LIVE_JIRA")
    _, auth_missing = _jira_config(step_with, ctx)
    missing.extend(auth_missing)
    if require_issue_key:
        issue_key = str(step_with.get("issueKey") or ctx.get("vars", {}).get("issueKey") or "").strip()
        if not issue_key:
            missing.append("with.issueKey or vars.issueKey")

    return {"ok": not missing, "missing": sorted(set(missing)), "mode": "live"}


def _jira_auth_header(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _jira_request_json(
    *,
    method: str,
    base_url: str,
    path: str,
    email: str,
    token: str,
    timeout_sec: int,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    url = f"{base_url}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Accept": "application/json", "Authorization": _jira_auth_header(email, token)}
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url=url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed: Any = {}
            if body.strip():
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = {"raw": body}
            return int(response.status), parsed
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        message = body.strip()[:400] if body.strip() else err.reason
        raise StepExecutionError(f"jira request failed ({err.code}) {method.upper()} {path}: {message}") from err
    except urllib.error.URLError as err:
        raise StepExecutionError(f"jira request failed {method.upper()} {path}: {err.reason}") from err


def _jira_request_attachment(
    *,
    base_url: str,
    issue_key: str,
    file_path: str,
    api_version: int = 2,
    email: str,
    token: str,
    timeout_sec: int,
) -> tuple[int, Any]:
    path = f"/rest/api/{int(api_version)}/issue/{quote(issue_key)}/attachments"
    url = f"{base_url}{path}"
    file_obj = Path(file_path)
    payload = file_obj.read_bytes()
    content_type = mimetypes.guess_type(file_obj.name)[0] or "application/octet-stream"
    boundary = f"----continuum-{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_obj.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": _jira_auth_header(email, token),
        "X-Atlassian-Token": "no-check",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            text = response.read().decode("utf-8", errors="replace")
            parsed: Any = {}
            if text.strip():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"raw": text}
            return int(response.status), parsed
    except urllib.error.HTTPError as err:
        body_text = err.read().decode("utf-8", errors="replace")
        message = body_text.strip()[:400] if body_text.strip() else err.reason
        raise StepExecutionError(f"jira attachment upload failed ({err.code}) for '{file_obj.name}': {message}") from err
    except urllib.error.URLError as err:
        raise StepExecutionError(f"jira attachment upload failed for '{file_obj.name}': {err.reason}") from err


def _infer_required_steps(step_with: dict[str, Any], *, labels: list[str], components: list[str]) -> list[str]:
    requirements_map = step_with.get("requirementsMap") if isinstance(step_with.get("requirementsMap"), dict) else {
        "postman": ["run_postman"],
        "mongo": ["verify_mongo"],
        "sql": ["verify_sql"],
        "logs": ["collect_logs"],
        "jira": ["jira.comment", "jira.attach", "jira.publish"],
    }
    required_steps: set[str] = {str(v).strip() for v in (step_with.get("requiredSteps") or []) if str(v).strip()}
    tokens = [*labels, *components]
    for token in tokens:
        lower_token = token.lower()
        for matcher, mapped in requirements_map.items():
            if str(matcher).lower() not in lower_token:
                continue
            if isinstance(mapped, list):
                for item in mapped:
                    if isinstance(item, str) and item.strip():
                        required_steps.add(item.strip())
    return sorted(required_steps)


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
            elif key.startswith("secret."):
                secret_name = key.split(".", 1)[1]
                if _lookup(f"env.{secret_name}", ctx) is None:
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
            if key.startswith("secret."):
                secret_name = key.split(".", 1)[1]
                return str(_lookup(f"env.{secret_name}", ctx) or "")
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




class HttpRequestPlugin:
    type = "http.request"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        url = step_with.get("url")
        if not isinstance(url, str) or not url.strip():
            raise StepExecutionError("http.request requires with.url")
        method = str(step_with.get("method") or "GET").upper()
        headers = dict(step_with.get("headers") or {})
        timeout_sec = int(step_with.get("timeoutSec", 30))
        expect_status = step_with.get("expectStatus")
        data = step_with.get("json")

        request_body = None
        if data is not None:
            request_body = json.dumps(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url=url, method=method, headers={str(k): str(v) for k, v in headers.items()}, data=request_body)
        ok = False
        status = None
        body = ""
        error = None
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                status = int(response.status)
                body = response.read().decode("utf-8", errors="replace")
                ok = True
        except urllib.error.HTTPError as err:
            status = int(err.code)
            body = err.read().decode("utf-8", errors="replace")
            error = str(err)
        except Exception as err:
            error = str(err)

        if expect_status is not None:
            ok = ok and int(status or 0) == int(expect_status)
        else:
            ok = ok and status is not None and 200 <= int(status) < 300

        details = {"ok": ok, "url": url, "method": method, "status": status, "expectStatus": expect_status, "error": error}
        step_dir = Path(ctx["step_dir"](step_index, step_name))
        step_dir.mkdir(parents=True, exist_ok=True)
        body_path = step_dir / "response.body.txt"
        body_path.write_text(body, encoding="utf-8")
        details_path = ctx["write_json"](str(step_dir), "response.json", details)
        return StepResult(ok=ok, details=details, evidence_paths=[details_path, str(body_path)], exports={"httpStatus": status})


class MongoDbVerifyPlugin:
    type = "mongodb.verify"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            import pymongo  # type: ignore  # noqa: F401
            return {"ok": True, "missing": []}
        except Exception:
            return {"ok": False, "missing": ["pymongo"]}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        return MongoVerifyPlugin().run(step_name=step_name, step_with=step_with, ctx=ctx, step_index=step_index)


class PreflightChecklistPlugin:
    type = "preflight.checklist"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        env_required = [str(v).strip() for v in (step_with.get("envRequired") or []) if str(v).strip()]
        commands = [str(v).strip() for v in (step_with.get("commands") or []) if str(v).strip()]
        files = [str(v).strip() for v in (step_with.get("files") or []) if str(v).strip()]

        env_missing = [key for key in env_required if not ctx.get("env", {}).get(key)]
        cmd_missing = [cmd for cmd in commands if resolve_command(cmd) is None]
        file_missing = [path for path in files if not Path(path).is_file()]

        details = {
            "ok": not env_missing and not cmd_missing and not file_missing,
            "envRequired": env_required,
            "commands": commands,
            "files": files,
            "envMissing": env_missing,
            "commandsMissing": cmd_missing,
            "filesMissing": file_missing,
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "preflight.json", details)
        return StepResult(ok=details["ok"], details=details, evidence_paths=[path], exports={"preflightOk": details["ok"]})


class GatewayCheckPlugin:
    type = "gateway.check"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        endpoint = str(step_with.get("endpoint") or step_with.get("url") or "").strip()
        if not endpoint:
            raise StepExecutionError("gateway.check requires with.endpoint")
        timeout_sec = max(1, int(step_with.get("timeoutSec", 5)))
        retries = max(1, int(step_with.get("retries", 2)))
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, port)})
            dns = {"ok": True, "host": host, "addresses": addresses}
        except Exception as err:
            dns = {"ok": False, "host": host, "classification": "dns", "error": str(err)}

        ok = False
        response: dict[str, Any] = {"classification": "unreachable"}
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(url=endpoint, method="GET")
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    code = int(resp.status)
                    response = {"attempt": attempt, "status": code, "classification": "ok" if 200 <= code < 300 else "http_5xx"}
                    if 200 <= code < 300:
                        ok = True
                        break
            except urllib.error.HTTPError as err:
                code = int(err.code)
                response = {
                    "attempt": attempt,
                    "status": code,
                    "classification": "auth" if code in {401, 403} else "http_5xx" if code >= 500 else "http_error",
                    "error": str(err),
                }
            except TimeoutError as err:
                response = {"attempt": attempt, "classification": "timeout", "error": str(err)}
            except Exception as err:
                response = {"attempt": attempt, "classification": "network", "error": str(err)}

        details = {
            "ok": ok,
            "endpoint": endpoint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dns": dns,
            "response": response,
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "gateway_check.json", details)
        return StepResult(ok=ok, details=details, evidence_paths=[path], exports={"gatewayHealthy": ok})


class PostmanRunPlugin:
    type = "postman.run"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        newman = resolve_newman_executable()
        return {"ok": newman is not None, "missing": ["newman"] if newman is None else []}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        step_dir = Path(ctx["step_dir"](step_index, step_name))
        step_dir.mkdir(parents=True, exist_ok=True)
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        run_id = str(ctx.get("run_id") or "")
        env_var = dict(step_with.get("envVar") or {})
        env_var.update({"traceId": trace_id, "runId": run_id})
        newman = resolve_newman_executable()
        if newman is None:
            allow_missing = bool(step_with.get("allowMissingDependency", False))
            path = ctx["write_json"](
                ctx["step_dir"](step_index, step_name),
                "missing-dependency.json",
                {
                    "missing": "newman",
                    "message": "postman.run requires newman",
                    "allowMissingDependency": allow_missing,
                    "envVar": env_var,
                    "headers": {
                        "X-Continuum-Run-Id": run_id,
                        "X-Continuum-Trace-Id": trace_id,
                    },
                },
            )
            return StepResult(ok=allow_missing, details={"error": "postman.run requires newman"}, evidence_paths=[path], exports={"postmanTraceId": trace_id})
        collection = step_with.get("collection")
        if not isinstance(collection, str) or not collection.strip():
            raise StepExecutionError("postman.run requires with.collection")

        command = [newman, "run", collection]
        environment = step_with.get("environment")
        if isinstance(environment, str) and environment.strip():
            command.extend(["-e", environment])
        iterations = step_with.get("iterations")
        if iterations is not None:
            command.extend(["--iteration-count", str(int(iterations))])

        reporters_raw = step_with.get("reporters", "cli,json")
        reporters = [item.strip() for item in str(reporters_raw).split(",") if item.strip()]
        command.extend(["--reporters", ",".join(reporters)])
        report_json = step_dir / "newman-report.json"
        report_junit = step_dir / "newman-report.xml"
        if "json" in reporters:
            command.extend(["--reporter-json-export", str(report_json)])
        if "junit" in reporters:
            command.extend(["--reporter-junit-export", str(report_junit)])

        for key, value in env_var.items():
            command.extend(["--env-var", f"{key}={value}"])

        timeout_sec = int(step_with.get("timeoutSec", 900))
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_sec,
        )
        stdout_path = step_dir / "newman.stdout.log"
        stderr_path = step_dir / "newman.stderr.log"
        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")

        path = ctx["write_json"](
            ctx["step_dir"](step_index, step_name),
            "newman-summary.json",
            {
                "returncode": int(proc.returncode),
                "command": command,
                "envVar": env_var,
                "headers": {
                    "X-Continuum-Run-Id": run_id,
                    "X-Continuum-Trace-Id": trace_id,
                },
                "stdoutPath": str(stdout_path),
                "stderrPath": str(stderr_path),
                "reportJson": str(report_json) if report_json.exists() else None,
                "reportJunit": str(report_junit) if report_junit.exists() else None,
            },
        )
        ok = proc.returncode == 0
        return StepResult(
            ok=ok,
            details={"returncode": int(proc.returncode), "traceId": trace_id},
            evidence_paths=[path, str(stdout_path), str(stderr_path)],
            exports={"postmanTraceId": trace_id},
        )


class MongoVerifyPlugin:
    type = "mongo.verify"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        if not _live_mode_requested(step_with):
            return {"ok": True, "missing": [], "mode": "stub"}

        missing: list[str] = []
        if not _connector_live_gate_enabled(ctx=ctx, connector="mongo"):
            missing.append("CONTINUUM_ENABLE_LIVE_CONNECTORS or CONTINUUM_ENABLE_LIVE_MONGO")
        uri = step_with.get("uri")
        db_name = step_with.get("db")
        if not isinstance(uri, str) or not uri.strip():
            missing.append("with.uri")
        if not isinstance(db_name, str) or not db_name.strip():
            missing.append("with.db")
        try:
            import pymongo  # type: ignore  # noqa: F401
        except Exception:
            missing.append("pymongo")
        return {"ok": not missing, "missing": sorted(set(missing)), "mode": "live"}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        auto_filter = bool(step_with.get("autoFilterTraceId", False))
        queries = step_with.get("queries") if isinstance(step_with.get("queries"), list) else []
        assertions = step_with.get("assert") if isinstance(step_with.get("assert"), list) else []
        applied = False

        if not _live_mode_requested(step_with):
            if isinstance(queries, list):
                for query in queries:
                    if not isinstance(query, dict):
                        continue
                    filter_obj = query.get("filter")
                    if auto_filter and isinstance(filter_obj, dict) and "traceId" not in filter_obj:
                        filter_obj["traceId"] = trace_id
                        applied = True
            payload = {
                "ok": True,
                "mode": "stub",
                "queries": queries,
                "traceId": trace_id,
                "traceQueryApplied": applied,
            }
            path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "assertions.json", payload)
            return StepResult(ok=True, details=payload, evidence_paths=[path], exports={"traceQueryApplied": applied})

        if not _connector_live_gate_enabled(ctx=ctx, connector="mongo"):
            raise StepExecutionError(
                "mongo.verify live mode requires CONTINUUM_ENABLE_LIVE_CONNECTORS=1 or CONTINUUM_ENABLE_LIVE_MONGO=1"
            )
        uri = step_with.get("uri")
        db_name = step_with.get("db")
        if not isinstance(uri, str) or not uri.strip():
            raise StepExecutionError("mongo.verify live mode requires with.uri")
        if not isinstance(db_name, str) or not db_name.strip():
            raise StepExecutionError("mongo.verify live mode requires with.db")

        try:
            import pymongo  # type: ignore
        except Exception as err:
            raise StepExecutionError("mongo.verify live mode requires pymongo") from err

        sample_limit = max(0, int(step_with.get("sampleLimit", 20)))
        timeout_ms = max(1000, int(step_with.get("serverSelectionTimeoutMs", 5000)))

        client = None
        query_results: dict[str, Any] = {}
        try:
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)  # type: ignore[attr-defined]
            client.admin.command("ping")
            database = client[str(db_name)]

            for query in queries:
                if not isinstance(query, dict):
                    continue
                query_name = str(query.get("name") or "").strip()
                collection_name = str(query.get("collection") or "").strip()
                if not query_name:
                    raise StepExecutionError("mongo.verify query requires name")
                if not collection_name:
                    raise StepExecutionError(f"mongo.verify query '{query_name}' requires collection")
                filter_obj = query.get("filter") if isinstance(query.get("filter"), dict) else {}
                filter_payload = dict(filter_obj)
                if auto_filter and trace_id and "traceId" not in filter_payload:
                    filter_payload["traceId"] = trace_id
                    applied = True
                projection = query.get("projection") if isinstance(query.get("projection"), dict) else None
                limit_raw = query.get("limit")
                query_limit = sample_limit
                if limit_raw is not None:
                    try:
                        query_limit = max(0, int(limit_raw))
                    except Exception:
                        query_limit = sample_limit

                collection = database[collection_name]
                count = int(collection.count_documents(filter_payload))
                cursor = collection.find(filter_payload, projection)
                docs: list[Any] = []
                if query_limit > 0 and hasattr(cursor, "limit"):
                    cursor = cursor.limit(query_limit)
                for idx, doc in enumerate(cursor):
                    if query_limit > 0 and not hasattr(cursor, "limit") and idx >= query_limit:
                        break
                    docs.append(_json_compatible(doc))
                query_results[query_name] = {
                    "collection": collection_name,
                    "count": count,
                    "filter": _json_compatible(filter_payload),
                    "sample": docs,
                }
        except StepExecutionError:
            raise
        except Exception as err:
            raise StepExecutionError(f"mongo.verify live execution failed: {err}") from err
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        assertion_results: list[dict[str, Any]] = []
        all_ok = True
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            query_name = str(assertion.get("query") or "")
            op = str(assertion.get("op") or "eq")
            expected = assertion.get("value", 0)
            actual = int((query_results.get(query_name) or {}).get("count", 0))
            ok = _compare_numeric(actual, op, expected)
            assertion_results.append({"query": query_name, "op": op, "expected": expected, "actual": actual, "ok": ok})
            all_ok = all_ok and ok

        payload = {
            "ok": all_ok,
            "mode": "live",
            "db": str(db_name),
            "traceId": trace_id,
            "traceQueryApplied": applied,
            "queryResults": query_results,
            "assertions": assertion_results,
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "assertions.json", payload)
        return StepResult(
            ok=all_ok,
            details=payload,
            evidence_paths=[path],
            exports={"traceQueryApplied": applied, "mongoAssertionsOk": all_ok},
        )


class SqlVerifyPlugin:
    type = "sql.verify"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        database = step_with.get("database")
        if not isinstance(database, str) or not database.strip():
            return {"ok": False, "missing": ["with.database"]}
        return {"ok": True, "missing": []}

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        database = step_with.get("database")
        if not isinstance(database, str) or not database.strip():
            raise StepExecutionError("sql.verify requires with.database (sqlite path)")
        queries = step_with.get("queries") if isinstance(step_with.get("queries"), list) else []
        assertions = step_with.get("assert") if isinstance(step_with.get("assert"), list) else []
        seed_statements = [str(v).strip() for v in (step_with.get("seedStatements") or []) if str(v).strip()]

        query_results: dict[str, Any] = {}
        conn = sqlite3.connect(database)
        try:
            for statement in seed_statements:
                conn.execute(statement)
            if seed_statements:
                conn.commit()
            for query in queries:
                if not isinstance(query, dict):
                    continue
                name = str(query.get("name") or "")
                sql = str(query.get("sql") or "")
                params = query.get("params") if isinstance(query.get("params"), list) else []
                if not name or not sql:
                    continue
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                query_results[name] = {
                    "count": len(rows),
                    "rows": [list(row) for row in rows],
                }
        finally:
            conn.close()

        assertion_results: list[dict[str, Any]] = []
        all_ok = True
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            query_name = str(assertion.get("query") or "")
            op = str(assertion.get("op") or "eq")
            expected = assertion.get("value", 0)
            actual = int((query_results.get(query_name) or {}).get("count", 0))
            ok = _compare_numeric(actual, op, expected)
            assertion_results.append({"query": query_name, "op": op, "expected": expected, "actual": actual, "ok": ok})
            all_ok = all_ok and ok

        payload = {"ok": all_ok, "database": database, "seedStatements": seed_statements, "queryResults": query_results, "assertions": assertion_results}
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "assertions.json", payload)
        return StepResult(ok=all_ok, details=payload, evidence_paths=[path], exports={"sqlAssertionsOk": all_ok})


class JiraFetchPlugin:
    type = "jira.fetch"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return _jira_preflight(step_with=step_with, ctx=ctx, require_issue_key=True)

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        issue_key = str(step_with.get("issueKey") or ctx["vars"].get("issueKey") or "").strip() or None
        issue_payload = step_with.get("issue") if isinstance(step_with.get("issue"), dict) else {}
        labels: list[str] = []
        components_raw: list[Any] = []
        source = "scenario"
        status_code: int | None = None
        fetched: dict[str, Any] = {}
        requested_live = _live_mode_requested(step_with)
        if requested_live:
            if not _connector_live_gate_enabled(ctx=ctx, connector="jira"):
                raise StepExecutionError(
                    "jira live mode requires CONTINUUM_ENABLE_LIVE_CONNECTORS=1 or CONTINUUM_ENABLE_LIVE_JIRA=1"
                )
            jira_cfg, missing = _jira_config(step_with, ctx)
            if missing:
                raise StepExecutionError(f"jira live mode missing configuration: {', '.join(missing)}")
            if not issue_key:
                raise StepExecutionError("jira.fetch live mode requires with.issueKey or vars.issueKey")
            fields = step_with.get("fields")
            if not isinstance(fields, list) or not fields:
                fields = ["labels", "components", "summary", "status", "issuetype", "priority"]
            fields_param = ",".join(str(v).strip() for v in fields if str(v).strip())
            endpoint = f"/rest/api/2/issue/{quote(issue_key)}"
            if fields_param:
                endpoint = f"{endpoint}?{urlencode({'fields': fields_param})}"
            status_code, fetched_payload = _jira_request_json(
                method="GET",
                base_url=jira_cfg["baseUrl"],
                path=endpoint,
                email=jira_cfg["email"],
                token=jira_cfg["token"],
                timeout_sec=int(jira_cfg["timeoutSec"]),
            )
            fields_payload = fetched_payload.get("fields") if isinstance(fetched_payload, dict) else {}
            fields_payload = fields_payload if isinstance(fields_payload, dict) else {}
            labels = [str(v).strip() for v in (fields_payload.get("labels") or []) if str(v).strip()]
            components_raw = fields_payload.get("components") if isinstance(fields_payload.get("components"), list) else []
            fetched = {
                "summary": fields_payload.get("summary"),
                "status": ((fields_payload.get("status") or {}).get("name") if isinstance(fields_payload.get("status"), dict) else fields_payload.get("status")),
                "issueType": ((fields_payload.get("issuetype") or {}).get("name") if isinstance(fields_payload.get("issuetype"), dict) else fields_payload.get("issuetype")),
                "priority": ((fields_payload.get("priority") or {}).get("name") if isinstance(fields_payload.get("priority"), dict) else fields_payload.get("priority")),
            }
            source = "jira-api"
        else:
            labels = [str(v).strip() for v in (issue_payload.get("labels") or []) if str(v).strip()]
            components_raw = issue_payload.get("components") or []

        components: list[str] = []
        if isinstance(components_raw, list):
            for item in components_raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        components.append(name)
                elif isinstance(item, str) and item.strip():
                    components.append(item.strip())

        required_steps = _infer_required_steps(step_with, labels=labels, components=components)

        details = {
            "issueKey": issue_key,
            "live": requested_live,
            "source": source,
            "statusCode": status_code,
            "labels": labels,
            "components": components,
            "requiredSteps": required_steps,
            "issue": fetched,
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "issue.json", details)
        return StepResult(ok=True, details=details, evidence_paths=[path], exports={"requiredSteps": required_steps})


class JiraCommentPlugin:
    type = "jira.comment"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return _jira_preflight(step_with=step_with, ctx=ctx, require_issue_key=True)

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        run_id = str(ctx.get("run_id") or "")
        trace_id = str(ctx.get("vars", {}).get("traceId") or "")
        status = str(ctx.get("vars", {}).get("status") or "completed")
        body = str(step_with.get("body") or f"Run {run_id} finished with status {status}. Trace {trace_id}. Report attached.")
        issue_key = str(step_with.get("issueKey") or ctx.get("vars", {}).get("issueKey") or "").strip() or None
        requested_live = _live_mode_requested(step_with)
        details: dict[str, Any] = {"ok": True, "body": body, "live": requested_live, "issueKey": issue_key}
        if requested_live:
            if not _connector_live_gate_enabled(ctx=ctx, connector="jira"):
                raise StepExecutionError(
                    "jira live mode requires CONTINUUM_ENABLE_LIVE_CONNECTORS=1 or CONTINUUM_ENABLE_LIVE_JIRA=1"
                )
            jira_cfg, missing = _jira_config(step_with, ctx)
            if missing:
                raise StepExecutionError(f"jira live mode missing configuration: {', '.join(missing)}")
            if not issue_key:
                raise StepExecutionError("jira.comment live mode requires with.issueKey or vars.issueKey")
            status_code, payload = _jira_request_json(
                method="POST",
                base_url=jira_cfg["baseUrl"],
                path=f"/rest/api/2/issue/{quote(issue_key)}/comment",
                email=jira_cfg["email"],
                token=jira_cfg["token"],
                timeout_sec=int(jira_cfg["timeoutSec"]),
                payload={"body": body},
            )
            details.update(
                {
                    "statusCode": status_code,
                    "commentId": payload.get("id") if isinstance(payload, dict) else None,
                }
            )
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "comment.json", details)
        return StepResult(ok=True, details=details, evidence_paths=[path])


class JiraAttachPlugin:
    type = "jira.attach"

    def preflight(self, *, step_with: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return _jira_preflight(step_with=step_with, ctx=ctx, require_issue_key=True)

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        files = resolve_attach_files(step_with, ctx["run_dir"])
        issue_key = str(step_with.get("issueKey") or ctx.get("vars", {}).get("issueKey") or "").strip() or None
        requested_live = _live_mode_requested(step_with)
        details: dict[str, Any] = {"files": files, "live": requested_live, "issueKey": issue_key}
        if requested_live:
            if not _connector_live_gate_enabled(ctx=ctx, connector="jira"):
                raise StepExecutionError(
                    "jira live mode requires CONTINUUM_ENABLE_LIVE_CONNECTORS=1 or CONTINUUM_ENABLE_LIVE_JIRA=1"
                )
            jira_cfg, missing = _jira_config(step_with, ctx)
            if missing:
                raise StepExecutionError(f"jira live mode missing configuration: {', '.join(missing)}")
            if not issue_key:
                raise StepExecutionError("jira.attach live mode requires with.issueKey or vars.issueKey")
            max_bytes = max(1, int(step_with.get("maxBytesPerFile", 10_000_000)))
            uploaded: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for file_path in files:
                path_obj = Path(file_path)
                size = path_obj.stat().st_size if path_obj.exists() else 0
                if size > max_bytes:
                    skipped.append({"path": file_path, "reason": "max-bytes", "size": size})
                    continue
                status_code, payload = _jira_request_attachment(
                    base_url=jira_cfg["baseUrl"],
                    issue_key=issue_key,
                    file_path=file_path,
                    api_version=2,
                    email=jira_cfg["email"],
                    token=jira_cfg["token"],
                    timeout_sec=int(jira_cfg["timeoutSec"]),
                )
                attachment_payload = payload if isinstance(payload, list) else [payload]
                attachment_id = None
                if attachment_payload and isinstance(attachment_payload[0], dict):
                    attachment_id = attachment_payload[0].get("id")
                uploaded.append({"path": file_path, "statusCode": status_code, "attachmentId": attachment_id})
            details.update({"uploaded": uploaded, "skipped": skipped})
            ok = bool(uploaded)
        else:
            ok = bool(files)
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "resolved_files.json", details)
        return StepResult(ok=ok, details=details, evidence_paths=[path])


class JiraPublishPlugin:
    type = "jira.publish"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        run_dir = Path(str(ctx.get("run_dir") or ""))
        summary_path = run_dir / "summary.json"
        manifest_path = run_dir / "manifest.json"
        signature_path = run_dir / "bundle_signature.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        signature = json.loads(signature_path.read_text(encoding="utf-8")) if signature_path.is_file() else {}

        policy = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
        policy_post = policy.get("post") if isinstance(policy.get("post"), dict) else {}
        issue_key = str(step_with.get("issueKey") or ctx.get("vars", {}).get("issueKey") or "").strip() or None
        status = str(summary.get("status") or "unknown")
        trace_id = str(summary.get("traceId") or ctx.get("vars", {}).get("traceId") or "")
        post_missing = policy_post.get("violations") if isinstance(policy_post.get("violations"), list) else []
        gate_missing = policy.get("missing") if isinstance(policy.get("missing"), list) else []
        policy_missing = [str(item) for item in [*post_missing, *gate_missing]]
        policy_ok = bool(policy_post.get("ok", policy.get("ok", False)))
        key_id = str(signature.get("keyId") or "")
        manifest_sha = str(signature.get("manifest_sha256") or "")

        attach = [str(v).strip() for v in (step_with.get("attach") or []) if str(v).strip()]
        files = resolve_attach_files({"files": attach}, str(run_dir)) if attach else []
        report_url = str(step_with.get("reportUrl") or "").strip()

        run_id = str(ctx.get("run_id") or "").strip()
        comment_lines = [
            "Continuum provable run summary",
            f"- runId: {run_id or 'n/a'}",
            f"- status: {status}",
            f"- traceId: {trace_id or 'n/a'}",
            f"- policy.ok: {policy_ok}",
            f"- policy.missing: {', '.join(policy_missing) if policy_missing else 'none'}",
            f"- signature.keyId: {key_id or 'n/a'}",
            f"- signature.manifest_sha256: {manifest_sha or 'n/a'}",
        ]
        if report_url:
            comment_lines.append(f"- report: {report_url}")
        body = str(step_with.get("body") or "\n".join(comment_lines))

        jira_cfg, missing_env = _jira_config(step_with, ctx)
        details: dict[str, Any] = {
            "issueKey": issue_key,
            "status": status,
            "traceId": trace_id,
            "policyOk": policy_ok,
            "policyMissing": policy_missing,
            "signature": {"keyId": key_id, "manifest_sha256": manifest_sha},
            "files": files,
            "reportUrl": report_url or None,
            "performed": False,
            "wouldPost": bool(issue_key),
            "missingConfig": missing_env,
        }

        if issue_key and not missing_env:
            status_code, payload = _jira_request_json(
                method="POST",
                base_url=jira_cfg["baseUrl"],
                path=f"/rest/api/2/issue/{quote(issue_key)}/comment",
                email=jira_cfg["email"],
                token=jira_cfg["token"],
                timeout_sec=int(jira_cfg["timeoutSec"]),
                payload={"body": body},
            )
            uploaded: list[dict[str, Any]] = []
            for file_path in files:
                up_code, up_payload = _jira_request_attachment(
                    base_url=jira_cfg["baseUrl"],
                    issue_key=issue_key,
                    file_path=file_path,
                    email=jira_cfg["email"],
                    token=jira_cfg["token"],
                    timeout_sec=int(jira_cfg["timeoutSec"]),
                )
                attachment_payload = up_payload if isinstance(up_payload, list) else [up_payload]
                attachment_id = None
                if attachment_payload and isinstance(attachment_payload[0], dict):
                    attachment_id = attachment_payload[0].get("id")
                uploaded.append({"path": file_path, "statusCode": up_code, "attachmentId": attachment_id})

            details.update(
                {
                    "performed": True,
                    "wouldPost": True,
                    "statusCode": status_code,
                    "commentId": payload.get("id") if isinstance(payload, dict) else None,
                    "uploaded": uploaded,
                }
            )
        else:
            details["note"] = "jira.publish ran in dry-run mode (missing issue key or Jira environment configuration)"

        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "jira_publish.json", details)
        return StepResult(ok=True, details=details, evidence_paths=[path])


class GitBranchPlugin:
    type = "git.branch"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        branch = str(step_with.get("branch") or "").strip()
        if not branch:
            raise StepExecutionError("git.branch requires with.branch")
        base = str(step_with.get("base") or "").strip()
        command = ["git", "checkout", "-B", branch]
        if base:
            command.append(base)
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        details = {
            "branch": branch,
            "base": base or None,
            "returncode": int(proc.returncode),
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "git-branch.json", details)
        return StepResult(ok=proc.returncode == 0, details=details, evidence_paths=[path], exports={"gitBranch": branch})


class GitCommitPlugin:
    type = "git.commit"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        message = str(step_with.get("message") or "").strip()
        if not message:
            raise StepExecutionError("git.commit requires with.message")
        paths = [str(v) for v in (step_with.get("paths") or ["."])]
        add_proc = subprocess.run(["git", "add", *paths], capture_output=True, text=True, check=False)
        commit_cmd = ["git", "commit", "-m", message]
        if bool(step_with.get("allowEmpty", False)):
            commit_cmd.append("--allow-empty")
        commit_proc = subprocess.run(commit_cmd, capture_output=True, text=True, check=False)
        details = {
            "paths": paths,
            "message": message,
            "addReturncode": int(add_proc.returncode),
            "commitReturncode": int(commit_proc.returncode),
            "stdout": (commit_proc.stdout or "").strip(),
            "stderr": (commit_proc.stderr or "").strip(),
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "git-commit.json", details)
        return StepResult(ok=add_proc.returncode == 0 and commit_proc.returncode == 0, details=details, evidence_paths=[path])


class GitPrPlugin:
    type = "git.pr"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        title = str(step_with.get("title") or "").strip()
        body = str(step_with.get("body") or "").strip()
        base = str(step_with.get("base") or "main").strip()
        if not title:
            raise StepExecutionError("git.pr requires with.title")
        if shutil.which("gh") is None:
            details = {
                "manualRequired": True,
                "reason": "gh cli not found",
                "title": title,
                "body": body,
                "base": base,
            }
            path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "git-pr.json", details)
            return StepResult(ok=True, details=details, evidence_paths=[path], exports={"prCreated": False})
        command = ["gh", "pr", "create", "--base", base, "--title", title, "--body", body]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        details = {
            "manualRequired": False,
            "command": command,
            "returncode": int(proc.returncode),
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "git-pr.json", details)
        return StepResult(ok=proc.returncode == 0, details=details, evidence_paths=[path], exports={"prCreated": proc.returncode == 0})


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
    # `"?` tolerates JSON-quoted key/value text (e.g. structured JSON log
    # lines like `{"token": "..."}`), which the previous unquoted-only
    # patterns never matched. Kept consistent with continuum/runtime.py
    # and continuum/publish.py, which redact the same secret shapes.
    patterns = [
        (r'(?i)(token"?\s*[=:]\s*"?)([^\s,;"]+)', r"\1[REDACTED]"),
        (r'(?i)(password"?\s*[=:]\s*"?)([^\s,;"]+)', r"\1[REDACTED]"),
        (r'(?i)(cookie"?\s*[=:]\s*"?)([^\s,;"]+)', r"\1[REDACTED]"),
        (r'(?i)(authorization"?\s*:\s*"?bearer\s+)([^\s,;"]+)', r"\1[REDACTED]"),
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


def _compare_numeric(actual: int, op: str, expected: Any) -> bool:
    try:
        expected_int = int(expected)
    except Exception:
        expected_int = 0
    operator = op.lower()
    if operator == "gte":
        return actual >= expected_int
    if operator == "lte":
        return actual <= expected_int
    if operator == "gt":
        return actual > expected_int
    if operator == "lt":
        return actual < expected_int
    if operator == "ne":
        return actual != expected_int
    return actual == expected_int


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
            elif source_type in {"splunk", "elk"}:
                endpoint = str(source.get("endpoint") or "").strip()
                query = str(source.get("query") or "").strip()
                token_env = str(source.get("tokenEnv") or "").strip()
                if endpoint and query:
                    resolved_sources.append(
                        {
                            "name": source_name,
                            "type": source_type,
                            "endpoint": endpoint,
                            "query": query,
                            "tokenEnv": token_env or None,
                        }
                    )

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
            src_id = src.get("path") or src.get("endpoint") or f"{src.get('command')} {' '.join(src.get('args', []))}".strip()
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
            elif src["type"] in {"splunk", "elk"}:
                token = ""
                if isinstance(src.get("tokenEnv"), str) and src["tokenEnv"]:
                    token = str(ctx.get("env", {}).get(src["tokenEnv"]) or "")
                query_string = str(src.get("query") or "")
                endpoint = str(src.get("endpoint") or "")
                params = urlencode({"q": query_string, "traceId": trace_id, "runId": run_id})
                url = endpoint + ("&" if "?" in endpoint else "?") + params
                headers = {"Accept": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                request = urllib.request.Request(url=url, headers=headers)
                try:
                    with urllib.request.urlopen(request, timeout=int(step_with.get("httpTimeoutSec", 30))) as response:
                        text = response.read().decode("utf-8", errors="replace")
                except Exception as err:
                    text = f"ERROR failed to fetch {src['type']} source: {err}"
                text = text[-max_bytes:]
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


class EvidenceUploadPlugin:
    type = "evidence.upload"

    def run(self, *, step_name: str, step_with: dict[str, Any], ctx: dict[str, Any], step_index: int) -> StepResult:
        from continuum.signing import sha256_file

        run_dir = Path(str(ctx.get("run_dir") or ""))
        vault_root = Path(str(step_with.get("vaultDir") or (os.environ.get("CONTINUUM_VAULT_DIR") or "vault")))

        manifest = run_dir / "manifest.json"
        if not manifest.is_file():
            return StepResult(ok=False, details={"error": "manifest.json missing"}, evidence_paths=[], exports={})

        manifest_sha = sha256_file(manifest)
        target = vault_root / manifest_sha

        allow_overwrite = bool(step_with.get("allowOverwrite", False))
        if target.exists() and not allow_overwrite:
            payload = {"ok": True, "skipped": True, "reason": "already exists", "vaultPath": str(target), "manifestSha256": manifest_sha, "vaultUri": f"file://{target}"}
            path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "evidence_vault.json", payload)
            return StepResult(ok=True, details=payload, evidence_paths=[path], exports={"vaultUri": f"file://{target}", "vaultSkipped": True})

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and allow_overwrite:
            shutil.rmtree(target, ignore_errors=True)

        shutil.copytree(run_dir, target)
        payload = {"ok": True, "skipped": False, "vaultPath": str(target), "vaultUri": f"file://{target}", "manifestSha256": manifest_sha}
        path = ctx["write_json"](ctx["step_dir"](step_index, step_name), "evidence_vault.json", payload)
        return StepResult(ok=True, details=payload, evidence_paths=[path], exports={"vaultUri": payload["vaultUri"], "vaultSkipped": False})


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
            HttpRequestPlugin(),
            PreflightChecklistPlugin(),
            GatewayCheckPlugin(),
            PostmanRunPlugin(),
            MongoVerifyPlugin(),
            MongoDbVerifyPlugin(),
            SqlVerifyPlugin(),
            JiraFetchPlugin(),
            JiraCommentPlugin(),
            JiraAttachPlugin(),
            JiraPublishPlugin(),
            EvidenceUploadPlugin(),
            GitBranchPlugin(),
            GitCommitPlugin(),
            GitPrPlugin(),
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
