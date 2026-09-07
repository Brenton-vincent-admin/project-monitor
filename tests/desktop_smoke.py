"""Opt-in desktop test: eight disposable Foot windows (six exhausted, two healthy) with fake Codex processes.

Run from the project root: .venv/bin/python tests/desktop_smoke.py --run
Uses no account credentials or network. Checks exhausted-only refresh, then a manual refresh of all eight fixture processes.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.codex import get_codex_sessions, restart_all_codex_sessions, _active_window_address, _focus_window


def main():
    if sys.argv[1:] != ['--run']:
        raise SystemExit(__doc__)
    original = _active_window_address()
    windows = []
    with tempfile.TemporaryDirectory(prefix='project-monitor-smoke-') as temp:
        root = Path(temp)
        work = root / 'project with spaces'
        work.mkdir()
        fake = root / 'codex'
        fake.write_text('''#!/usr/bin/python3
import ctypes, json, os, sys, time, tty
from datetime import datetime, timezone
from pathlib import Path
ctypes.CDLL(None).prctl(15, b"codex", 0, 0, 0)
root = Path(os.environ['MONITOR_SMOKE_ROOT'])
session_id = sys.argv[2]
rollout = (root / ('rollout-test-' + session_id + '.jsonl')).open('a')
used = 100 if int(session_id[-12:]) < 6 and '--sandbox' not in sys.argv else 10
rollout.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
    'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
        'primary': {'used_percent': used, 'resets_at': time.time() + 3600},
        'credits': {'has_credits': False, 'unlimited': False}}}}) + '\\n')
rollout.flush()
with (root / (session_id + '.argv')).open('w') as record:
    json.dump(sys.argv[1:], record)
# Exercise abrupt termination while the terminal is in raw mode.
tty.setraw(sys.stdin.fileno())
while True:
    time.sleep(1)
''')
        fake.chmod(0o700)
        ids = {f'12345678-1234-1234-1234-{i:012d}' for i in range(8)}
        try:
            for index, session_id in enumerate(sorted(ids)):
                rc = root / f'bashrc-{index}'
                rc.write_text(
                    'export PATH=' + shlex.quote(str(root) + ':' + os.environ['PATH']) + '\n'
                    'export MONITOR_SMOKE_ROOT=' + shlex.quote(str(root)) + '\n'
                    'cd -- ' + shlex.quote(str(work)) + '\n'
                    'set -m\n'
                    'codex resume ' + session_id + ' 2>' + shlex.quote(str(root / f'fake-{index}.log')) + '\n'
                )
                windows.append(subprocess.Popen(
                    ['foot', '--app-id=project-monitor-smoke', '--title=Project Monitor test',
                     'bash', '--noprofile', '--rcfile', str(rc), '-i'],
                    stdout=subprocess.DEVNULL, stderr=(root / f'foot-{index}.log').open('w')))
            deadline = time.monotonic() + 12
            sessions = []
            while time.monotonic() < deadline:
                sessions = [s for s in get_codex_sessions() if s.cwd == str(work) and s.session_id in ids]
                if len(sessions) == 8:
                    break
                time.sleep(.2)
            if len(sessions) != 8:
                print(subprocess.run(['ps', '-C', 'codex,bash,foot,python3', '-o', 'pid,ppid,pgid,tpgid,tty,comm'], capture_output=True, text=True).stdout)
                print('Detected:', get_codex_sessions())
                for log in root.glob('*.log'):
                    print(log.name, log.read_text())
            assert len(sessions) == 8, f'Found {len(sessions)} fixture sessions, expected 8'
            started = time.monotonic()
            count, summary = restart_all_codex_sessions(sessions)
            print(summary, flush=True)
            assert count == 6, summary
            for session_id in ids:
                args = json.loads((root / (session_id + '.argv')).read_text())
                if int(session_id[-12:]) >= 6:
                    assert args == ['resume', session_id], args
                    continue
                assert args == ['resume', session_id, '--cd', str(work), '--sandbox',
                                'danger-full-access', '--ask-for-approval', 'never'], args
            print(f'PASS: six exhausted chats resumed with Full Access; two healthy chats untouched, in {time.monotonic() - started:.1f}s', flush=True)
            sessions = [s for s in get_codex_sessions() if s.cwd == str(work) and s.session_id in ids]
            assert len(sessions) == 8
            started = time.monotonic()
            count, summary = restart_all_codex_sessions(sessions, exhausted_only=False)
            assert count == 8, summary
            print(f'PASS: manual refresh resumed all eight open chats in {time.monotonic() - started:.1f}s', flush=True)

        finally:
            for window in windows:
                if window.poll() is None:
                    window.terminate()
            for window in windows:
                try:
                    window.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    window.kill()
                    window.wait(timeout=3)
            if original:
                _focus_window(original)


if __name__ == '__main__':
    main()
