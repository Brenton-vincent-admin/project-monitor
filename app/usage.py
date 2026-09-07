"""Read OpenAI account limits in disposable Codex profiles, without switching."""
import json
import math
import os
import select
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

FRESH_SECONDS = 600
NEAR_LIMIT_PERCENT = 80


def epoch(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_usage(result):
    groups = result.get('rateLimitsByLimitId') or {'codex': result.get('rateLimits')}
    windows, reasons = [], []
    if not isinstance(groups, dict):
        raise ValueError('Invalid usage response')
    for key, group in groups.items():
        if not isinstance(group, dict):
            continue
        reason = group.get('rateLimitReachedType')
        if isinstance(reason, str) and reason:
            reasons.append(reason)
        credits = group.get('credits') or {}
        fallback = isinstance(credits, dict) and bool(credits.get('hasCredits') or credits.get('unlimited'))
        for name in ('primary', 'secondary'):
            bucket = group.get(name)
            if not isinstance(bucket, dict):
                continue
            used, duration, reset = (bucket.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt'))
            if not all(number(v) for v in (used, duration, reset)) or duration <= 0:
                continue
            windows.append({'limit': str(key), 'minutes': duration,
                            'used': max(0, min(100, used)), 'reset': reset,
                            'credit_fallback': fallback})
    resets = result.get('rateLimitResetCredits') or {}
    count = resets.get('availableCount') if isinstance(resets, dict) else None
    return {'windows': windows, 'reasons': reasons,
            'reset_credits': count if number(count) else None}


def usage_view(account, now=None):
    """Keep unknown/stale/reset-passed data distinct from confirmed capacity."""
    account = dict(account)
    now = time.time() if now is None else now
    try:
        data = json.loads(account.get('usage_json') or '{}')
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw_windows = data.get('windows')
    windows = []
    for window in raw_windows if isinstance(raw_windows, list) else []:
        if (isinstance(window, dict) and isinstance(window.get('limit'), str)
                and all(number(window.get(key)) for key in ('used', 'minutes', 'reset'))
                and 0 <= window['used'] <= 100 and window['minutes'] > 0
                and 0 < window['reset'] <= 253402300799):
            windows.append(window)
    reasons = data.get('reasons')
    reasons = [r for r in reasons if isinstance(r, str) and r] if isinstance(reasons, list) else []
    checked = epoch(account.get('usage_checked_at'))
    error = account.get('usage_error')
    state = 'Not checked'
    if error:
        state = 'Check failed'
    elif checked:
        state = 'Stale' if now - checked > FRESH_SECONDS or checked > now + 5 else 'Unknown'
        if state != 'Stale':
            if reasons:
                state = 'Limit reached'
            elif any(w['reset'] > now and w['used'] >= 100 and not w.get('credit_fallback') for w in windows):
                state = 'Limit reached'
            elif any(w['reset'] <= now for w in windows):
                state = 'Check reset'
            elif windows:
                used = max(w['used'] for w in windows)
                state = 'Nearly used up' if used >= NEAR_LIMIT_PERCENT else 'Ready'
    fresh = state in ('Ready', 'Nearly used up', 'Limit reached')
    # A local exhaustion mark newer than the server snapshot wins until rechecked.
    cooldown = epoch(account.get('cooldown_until'))
    if cooldown > now and (not fresh or checked <= epoch(account.get('last_used_at'))):
        state = 'Cooling down'
    reset_windows = [w['reset'] for w in windows if w['reset'] > now and w['used'] >= 100 and not w.get('credit_fallback')]
    reset = max(reset_windows) if reset_windows else min((w['reset'] for w in windows if w['reset'] > now), default=0)
    if state == 'Cooling down':
        reset = cooldown
    elif reasons:
        # A workspace credit block is not promised to clear at a quota reset.
        reset = 0
    return {'state': state, 'windows': windows, 'reset': reset,
            'checked': checked, 'error': error, 'reasons': reasons,
            'reset_credits': data.get('reset_credits'),
            'remaining': min((100 - w['used'] for w in windows), default=0),
            'blocked': state in ('Limit reached', 'Cooling down')}


def _stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    for stream in (process.stdin, process.stdout):
        if stream:
            stream.close()


def _response(process, request_id, stop, timeout=12):
    deadline, pending = time.monotonic() + timeout, b''
    while not stop.is_set() and time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], .1)
        if not ready:
            continue
        chunk = os.read(process.stdout.fileno(), 65536)
        if not chunk:
            return None
        pending += chunk
        if len(pending) > 2 * 1024 * 1024:
            return None
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('id') == request_id:
                return event
    return None


def fetch_usage(token, stop=None):
    """Return (snapshot, error). No credentials or server error text leave this call."""
    stop = stop or Event()
    try:
        with tempfile.TemporaryDirectory(prefix='project-monitor-usage-') as profile:
            Path(profile, 'config.toml').write_text('cli_auth_credentials_store = "file"\n')
            env = os.environ.copy()
            env['CODEX_HOME'] = profile
            for key in ('CODEX_ACCESS_TOKEN', 'OPENAI_API_KEY'):
                env.pop(key, None)
            login = subprocess.Popen(['codex', 'login', '--with-access-token'],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, env=env)
            try:
                login.stdin.write(token.encode())
                login.stdin.close()
                deadline = time.monotonic() + 15
                while login.poll() is None and not stop.wait(.1):
                    if time.monotonic() >= deadline:
                        return None, 'Login check timed out'
                if stop.is_set():
                    return None, 'Cancelled'
                if login.returncode:
                    return None, 'Login check failed'
            finally:
                _stop_process(login)
            server = subprocess.Popen(['codex', 'app-server', '--stdio'],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, env=env)
            try:
                def send(message):
                    server.stdin.write((json.dumps(message) + '\n').encode())
                    server.stdin.flush()
                send({'method': 'initialize', 'id': 0, 'params': {
                    'clientInfo': {'name': 'project_monitor', 'version': '0.1.0'}}})
                response = _response(server, 0, stop)
                if not response or 'result' not in response:
                    return None, 'Usage service unavailable'
                send({'method': 'initialized', 'params': {}})
                send({'method': 'account/rateLimits/read', 'id': 1})
                response = _response(server, 1, stop)
                if not response or not isinstance(response.get('result'), dict):
                    return None, 'Usage unavailable; check connection or login'
                return normalize_usage(response['result']), None
            finally:
                _stop_process(server)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, 'Usage check unavailable'


class UsageWorker(QThread):
    account_ready = pyqtSignal(int, str, object, object, str)
    progress = pyqtSignal(int, int)

    def __init__(self, accounts, parent=None):
        super().__init__(parent)
        self.accounts = [dict(a) for a in accounts]
        self.stop_event = Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        for index, account in enumerate(self.accounts):
            if self.stop_event.is_set():
                break
            self.progress.emit(index + 1, len(self.accounts))
            try:
                data, error = fetch_usage(account['token'], self.stop_event)
            except Exception:
                data, error = None, 'Usage check unavailable'
            if not self.stop_event.is_set():
                checked = datetime.now(timezone.utc).isoformat()
                self.account_ready.emit(account['id'], account['token'], data, error, checked)
