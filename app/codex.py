import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import lru_cache


SESSION_FILE_RE = re.compile(
    r"rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CodexSession:
    pid: int
    tty: str
    cwd: str
    session_id: str | None
    terminal_pid: int | None
    terminal_address: str | None
    start_time: int | None = None
    shell_pid: int | None = None
    shell_start_time: int | None = None


def login_with_token(token):
    """Log in to Codex with an access token. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["codex", "login", "--with-access-token"],
            input=token,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, "Logged in successfully"
        else:
            msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, msg
    except FileNotFoundError:
        return False, "codex CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "Login command timed out"


def logout():
    """Log out of Codex. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["codex", "logout"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, "Logged out"
        else:
            msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, msg
    except FileNotFoundError:
        return False, "codex CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "Logout command timed out"


def get_status():
    """Check Codex login status. Returns (logged_in: bool, info: str)."""
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = result.stdout.strip() + "\n" + result.stderr.strip()
        logged_in = result.returncode == 0 and "not logged" not in output.lower()
        return logged_in, output.strip()
    except FileNotFoundError:
        return False, "codex CLI not found"
    except subprocess.TimeoutExpired:
        return False, "Status unavailable: Codex timed out"
    except OSError:
        return False, "Status unavailable: could not run Codex"


def check_service_connection():
    """Bounded, credential-free reachability check before any account mutation."""
    try:
        result = subprocess.run(
            # This endpoint rejects HEAD with 405, even while online. Use GET
            # and discard the body; an unauthenticated 401 is expected.
            ["curl", "--silent", "--output", "/dev/null",
             "--connect-timeout", "2", "--max-time", "4",
             "--write-out", "%{http_code}", "https://chatgpt.com/backend-api/wham/usage"],
            capture_output=True, text=True, timeout=5,
        )
        # An unauthenticated response still proves that the service is reachable.
        if result.returncode == 0 and result.stdout.strip() in {"200", "401", "403"}:
            return True, "Service reachable"
    except (OSError, subprocess.SubprocessError):
        pass
    return False, "Offline or Codex service unavailable — accounts and chats were left untouched"


def _read_app_server_response(process, request_id, timeout=8.0):
    """Read JSONL until the requested app-server response arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            [process.stdout], [], [], max(0, deadline - time.monotonic())
        )
        if not ready:
            break
        line = process.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            return message
    return None


def _extract_rate_limit(result, preferred_window_minutes=300):
    """Select the Codex quota bucket matching the configured five-hour window."""
    if not isinstance(result, dict):
        return None

    groups = []
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        groups.extend(by_id.values())
    fallback_group = result.get("rateLimits")
    if isinstance(fallback_group, dict):
        groups.append(fallback_group)

    candidates = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for bucket_name in ("primary", "secondary"):
            bucket = group.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            duration = bucket.get("windowDurationMins")
            resets_at = bucket.get("resetsAt")
            if not isinstance(duration, (int, float)) or not isinstance(
                resets_at, (int, float)
            ):
                continue
            candidates.append(
                {
                    "limit_id": group.get("limitId"),
                    "bucket": bucket_name,
                    "used_percent": bucket.get("usedPercent"),
                    "window_minutes": int(duration),
                    "resets_at": int(resets_at),
                }
            )

    for candidate in candidates:
        if candidate["window_minutes"] == preferred_window_minutes:
            return candidate
    return candidates[0] if candidates else None


def get_codex_rate_limit(preferred_window_minutes=300):
    """Fetch the active ChatGPT account's Codex quota window via app-server."""
    process = None
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        initialize = {
            "method": "initialize",
            "id": 0,
            "params": {
                "clientInfo": {
                    "name": "project_monitor",
                    "title": "Project Monitor",
                    "version": "0.1.0",
                }
            },
        }
        process.stdin.write(json.dumps(initialize) + "\n")
        process.stdin.flush()
        initialized = _read_app_server_response(process, 0)
        if not initialized or "result" not in initialized:
            return None

        process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
        process.stdin.write(
            json.dumps({"method": "account/rateLimits/read", "id": 1}) + "\n"
        )
        process.stdin.flush()
        response = _read_app_server_response(process, 1)
        if not response or "result" not in response:
            return None
        return _extract_rate_limit(response["result"], preferred_window_minutes)
    except (BrokenPipeError, FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def get_exhaustion_cooldown(fallback_seconds):
    """Return (UTC reset timestamp, source) for the active account."""
    now = datetime.now(timezone.utc)
    preferred_minutes = max(1, round(fallback_seconds / 60))
    limit = get_codex_rate_limit(preferred_minutes)
    if limit:
        reset = datetime.fromtimestamp(limit["resets_at"], timezone.utc)
        if reset > now:
            return reset.isoformat(), "OpenAI reset time"
    return (now + timedelta(seconds=fallback_seconds)).isoformat(), "five-hour fallback"


def _proc_stat(pid, proc_root=Path("/proc")):
    """Return (parent pid, foreground pgrp), handling spaces in process names."""
    try:
        raw = (proc_root / str(pid) / "stat").read_text()
        fields = raw[raw.rfind(")") + 2 :].split()
        return int(fields[1]), int(fields[5])
    except (OSError, ValueError, IndexError):
        return None, None


def _tty_for_pid(pid, proc_root=Path("/proc")):
    try:
        tty = os.readlink(proc_root / str(pid) / "fd" / "0")
        return tty if tty.startswith("/dev/") else None
    except OSError:
        return None


def _start_time(pid, proc_root=Path("/proc")):
    try:
        raw = (proc_root / str(pid) / "stat").read_text()
        return int(raw[raw.rfind(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _session_id_for_pid(pid, proc_root=Path("/proc")):
    """Read the current conversation UUID from Codex's open rollout file."""
    fd_dir = proc_root / str(pid) / "fd"
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return None

    session_ids = set()
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        match = SESSION_FILE_RE.search(target)
        if match:
            session_ids.add(match.group(1))
    # Multiple rollout files may belong to subagents. Never guess a chat.
    return next(iter(session_ids)) if len(session_ids) == 1 else None


def _cwd_for_pid(pid, proc_root=Path("/proc")):
    try:
        return os.readlink(proc_root / str(pid) / "cwd")
    except OSError:
        return ""


def _hyprland_clients():
    """Return Hyprland toplevel PIDs mapped to their stable window addresses."""
    try:
        result = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        clients = json.loads(result.stdout) if result.returncode == 0 else []
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}

    mapped = {}
    ambiguous = set()
    for client in clients:
        pid = client.get("pid")
        address = client.get("address", "")
        if isinstance(pid, int) and re.fullmatch(r"0x[0-9a-fA-F]+", address):
            if pid in mapped:
                ambiguous.add(pid)
            mapped[pid] = address
    return {pid: address for pid, address in mapped.items() if pid not in ambiguous}


def _window_ancestor(pid, window_pids, proc_root=Path("/proc")):
    """Find the terminal window process that owns a Codex process."""
    seen = set()
    current = pid
    while current and current > 1 and current not in seen:
        seen.add(current)
        if current in window_pids:
            return current
        current, _ = _proc_stat(current, proc_root)
    return None


def get_codex_pids(proc_root=Path("/proc")):
    """Return interactive, foreground Codex TUI PIDs only."""
    pids = []
    try:
        result = subprocess.run(
            ["pgrep", "-x", "codex"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    tty = _tty_for_pid(pid, proc_root)
                    _, foreground_pgrp = _proc_stat(pid, proc_root)
                    if tty and foreground_pgrp == pid:
                        pids.append(pid)
    except Exception:
        pass
    return pids


def get_codex_sessions(proc_root=Path("/proc")):
    """Capture the terminal and exact conversation for every live Codex TUI."""
    windows = _hyprland_clients()
    sessions = []
    for pid in get_codex_pids(proc_root):
        terminal_pid = _window_ancestor(pid, windows, proc_root)
        parent, _ = _proc_stat(pid, proc_root)
        sessions.append(
            CodexSession(
                pid=pid,
                tty=_tty_for_pid(pid, proc_root) or "",
                cwd=_cwd_for_pid(pid, proc_root),
                session_id=_session_id_for_pid(pid, proc_root),
                terminal_pid=terminal_pid,
                terminal_address=windows.get(terminal_pid),
                start_time=_start_time(pid, proc_root),
                shell_pid=parent,
                shell_start_time=_start_time(parent, proc_root),
            )
        )
    return sessions


def _active_window_address():
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        address = json.loads(result.stdout).get("address", "")
        return address if re.fullmatch(r"0x[0-9a-fA-F]+", address) else None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _focus_window(address):
    if not re.fullmatch(r"0x[0-9a-fA-F]+", address or ""):
        return False
    action = f'hl.dsp.focus({{ window = "address:{address}" }})'
    try:
        result = subprocess.run(
            ["hyprctl", "dispatch", action],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    time.sleep(0.08)
    return _active_window_address() == address


def _type_resume_command(command):
    try:
        result = subprocess.run(
            ["wtype", "-d", "1", command, "-k", "Return"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _same_codex_process(session):
    """Guard against killing a PID that was recycled after a saved snapshot."""
    try:
        command = Path(f"/proc/{session.pid}/comm").read_text().strip()
    except OSError:
        return False
    return (
        command == "codex"
        and _tty_for_pid(session.pid) == session.tty
        and session.start_time is not None
        and _start_time(session.pid) == session.start_time
        and _session_id_for_pid(session.pid) == session.session_id
    )


def _shell_matches(session, foreground=False):
    """Require the original interactive shell, not a reused window or PID."""
    if not session.shell_pid or session.shell_start_time is None:
        return False
    try:
        name = Path(f"/proc/{session.shell_pid}/comm").read_text().strip()
    except OSError:
        return False
    _, foreground_pgrp = _proc_stat(session.shell_pid)
    return (
        name in {"bash", "zsh", "fish", "sh", "dash"}
        and _start_time(session.shell_pid) == session.shell_start_time
        and _tty_for_pid(session.shell_pid) == session.tty
        and (not foreground or foreground_pgrp == session.shell_pid)
    )


def _wait_for_shell(session, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _shell_matches(session, foreground=True):
            return True
        time.sleep(0.05)
    return False


def _restore_shell_keyboard(session):
    """Undo TUI keyboard reporting only after the original shell regains the tty."""
    if not _shell_matches(session, foreground=True):
        return False
    try:
        fd = os.open(session.tty, os.O_WRONLY | os.O_NOCTTY)
        try:
            # This process does not own the target controlling terminal, so
            # tcgetpgrp(fd) can return ENOTTY. Validate via /proc as above.
            if not os.isatty(fd) or not _shell_matches(session, foreground=True):
                return False
            # Kitty keyboard protocol: replace enhancement flags with zero.
            # https://sw.kovidgoyal.net/kitty/keyboard-protocol/#progressive-enhancement
            # SIGTERM can leave these enabled, garbling wtype input in Bash.
            reset = b"\x1b[=0u"
            if os.write(fd, reset) != len(reset):
                return False
        finally:
            os.close(fd)
        time.sleep(.15)
        return _shell_matches(session, foreground=True)
    except OSError:
        return False


def _resume_command(session, full_access=True):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", session.session_id or ""):
        return None
    if not session.cwd or any(c in session.cwd for c in "\r\n\0"):
        return None
    args = ["codex", "resume", session.session_id, "--cd", session.cwd]
    if full_access:
        args += ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]
    return shlex.join(args)


def _wait_for_resume(session, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for pid in get_codex_pids():
            if (pid != session.pid and _tty_for_pid(pid) == session.tty
                    and _session_id_for_pid(pid) == session.session_id):
                return True
        time.sleep(0.15)
    return False


def _quota_exhausted(limits, now):
    """Interpret the quota snapshot emitted by the installed Codex CLI."""
    if limits.get("rate_limit_reached_type"):
        return True
    credits = limits.get("credits") or {}
    if credits.get("has_credits") or credits.get("unlimited"):
        return False
    for name in ("primary", "secondary"):
        window = limits.get(name) or {}
        used, reset = window.get("used_percent"), window.get("resets_at")
        if (isinstance(used, (int, float)) and used >= 100
                and isinstance(reset, (int, float)) and reset > now):
            return True
    return False


def _reverse_rollout_lines(stream, max_line_bytes=256 * 1024):
    """Read backwards with bounded memory, skipping oversized conversation rows."""
    position = stream.seek(0, os.SEEK_END)
    pending = b""
    oversized = False
    while position:
        size = min(position, 64 * 1024)
        position -= size
        stream.seek(position)
        parts = stream.read(size).split(b"\n")
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            if not oversized:
                if len(part) + len(pending) <= max_line_bytes:
                    pending = part + pending
                else:
                    pending = b""
                    oversized = True
            if index > 0:
                if pending and not oversized:
                    yield pending
                pending = b""
                oversized = False
    if pending and not oversized:
        yield pending


@lru_cache(maxsize=128)
def _latest_rollout_quota(path, started_at, mtime_ns, file_size):
    # The stat fields invalidate cached results when the rollout changes. Large
    # unchanged logs need no repeated scan on the five-second monitor timer.
    with Path(path).open("rb") as stream:
        return _find_rollout_quota(_reverse_rollout_lines(stream), started_at)


def _find_rollout_quota(lines, started_at):
    for line in lines:
        try:
            event = json.loads(line)
            if event.get("type") != "event_msg":
                continue
            payload = event.get("payload", {})
            if payload.get("type") != "token_count":
                continue
            limits = payload.get("rate_limits")
            if not isinstance(limits, dict):
                continue
            recorded_at = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).timestamp()
            if recorded_at < started_at:
                return None
            return recorded_at, limits
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def _rollout_exhausted(path, started_at, now=None):
    """Use the latest quota from this process, even behind large log entries."""
    now = time.time() if now is None else now
    try:
        path = Path(path)
        stat = path.stat()
        quota = _latest_rollout_quota(str(path), started_at, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return False
    if quota is None:
        return False
    recorded_at, limits = quota
    return recorded_at <= now + 5 and _quota_exhausted(limits, now)


def _session_exhausted(session):
    if not _same_codex_process(session) or not session.session_id:
        return False
    started_at = (time.time() - time.clock_gettime(time.CLOCK_BOOTTIME)
                  + session.start_time / os.sysconf("SC_CLK_TCK"))
    try:
        for fd in Path(f"/proc/{session.pid}/fd").iterdir():
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            match = SESSION_FILE_RE.search(target)
            if match and match.group(1) == session.session_id:
                return _rollout_exhausted(target, started_at)
    except OSError:
        pass
    return False


def get_exhausted_codex_sessions(sessions=None):
    sessions = get_codex_sessions() if sessions is None else sessions
    return [session for session in sessions if _session_exhausted(session)]


def _wait_for_exit(sessions, timeout=4.0):
    deadline = time.monotonic() + timeout
    remaining = {session.pid: session for session in sessions}
    while remaining and time.monotonic() < deadline:
        remaining = {
            pid: session
            for pid, session in remaining.items()
            if _same_codex_process(session)
        }
        if remaining:
            time.sleep(0.05)
    return set(remaining)


def restart_all_codex_sessions(sessions=None, full_access=True, exhausted_only=True):
    """Restart open Codex TUIs, filtering for exhaustion by default.

    A process is never terminated unless its Hyprland window can be identified.
    Duplicate sessions in one window (for example terminal tabs/panes) are also
    left alone because simulated keyboard input cannot target them unambiguously.
    Returns ``(started_count, human_readable_summary)``.
    """
    sessions = list(sessions) if sessions is not None else get_codex_sessions()
    if not sessions:
        return 0, "No active Codex terminal sessions found"

    # Quota state is checked on live processes, never on closed chat history.
    exhausted = get_exhausted_codex_sessions(sessions) if exhausted_only else sessions
    if not exhausted:
        return 0, "No open Codex chats show an active usage limit; nothing was restarted"

    if not shutil.which("wtype"):
        return 0, "wtype is unavailable; no sessions were stopped"

    if not _active_window_address():
        return 0, "Could not read the active Hyprland window; no sessions were stopped"

    address_counts = {}
    for session in sessions:
        if session.terminal_address:
            address_counts[session.terminal_address] = (
                address_counts.get(session.terminal_address, 0) + 1
            )

    safe = [
        session
        for session in exhausted
        if session.terminal_address
        and address_counts.get(session.terminal_address) == 1
        and _resume_command(session, full_access)
        and _shell_matches(session)
        and _same_codex_process(session)
    ]
    skipped = len(exhausted) - len(safe)
    if not safe:
        return 0, f"Could not safely identify the exact chat, shell and window for {len(exhausted)} selected session(s); nothing was stopped"

    original_address = _active_window_address()
    failures = []
    started = 0
    try:
        for session in safe:
            # Check focus before stopping anything, then handle one terminal
            # at a time so a failed focus cannot strand every conversation.
            if (not _same_codex_process(session)
                    or (exhausted_only and not _session_exhausted(session))
                    or not _focus_window(session.terminal_address)):
                failures.append(session)
                continue
            try:
                os.kill(session.pid, signal.SIGTERM)
            except OSError:
                failures.append(session)
                continue
            if (_wait_for_exit([session]) or not _wait_for_shell(session)
                    or not _restore_shell_keyboard(session)
                    or not _focus_window(session.terminal_address)
                    or not _shell_matches(session, foreground=True)):
                failures.append(session)
                continue
            command = _resume_command(session, full_access)
            if _type_resume_command(command) and _wait_for_resume(session):
                started += 1
            else:
                failures.append(session)
    finally:
        if original_address:
            _focus_window(original_address)

    untouched = skipped
    failed = len(failures)
    details = [f"restarted {started} session(s)"]
    if untouched:
        details.append(f"left {untouched} unidentified or ambiguous session(s) untouched")
    if failed:
        details.append(f"could not restart {failed} session(s)")
    summary = "; ".join(details).capitalize()
    if failures:
        summary += "\n\nManual recovery commands (run in the matching terminal):\n"
        summary += "\n".join(
            f"{session.tty}: {_resume_command(session, full_access)}"
            for session in failures
        )
    return started, summary


def check_exhaustion():
    """A closed process or login failure is not evidence of quota exhaustion."""
    sessions = get_exhausted_codex_sessions()
    if sessions:
        return True, f"{len(sessions)} open Codex chat(s) reached their usage limit"
    return False, "No open Codex chats show an active usage limit"
