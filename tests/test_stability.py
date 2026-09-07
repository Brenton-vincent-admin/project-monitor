import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_switch
from tests.test_theme import DARK, LIGHT
from app.usage import usage_view


class StabilityTests(unittest.TestCase):
    def test_repeated_theme_changes_never_query_closed_database(self):
        f = test_switch.SwitchIntegrationTests()
        f.setUpClass(); f.setUp()
        theme = f.window.theme
        paths = theme.paths
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'colors.toml'
                theme.paths = [path]
                f.db.close()
                # Reproduce the exact reported crash, including a still-alive
                # Qt window whose database has already closed.
                with patch.object(f.db, 'get_all_accounts', side_effect=AssertionError('Theme queried database')):
                    for index in range(30):
                        path.write_text(LIGHT if index % 2 else DARK)
                        theme.refresh()
                        f.app.processEvents()
                f.window._closing = True
                f.window._usage_received(f.new, 'fake-new', {}, None, '')
                f.window._safe_tick()
        finally:
            theme.paths = paths
            theme.refresh()
            f.tearDown()

    def test_invalid_cached_data_does_not_crash_ui_or_claim_ready(self):
        from datetime import datetime, timezone
        for payload in ([], None, {'windows': None}, {'windows': [None, {}]},
                        {'windows': [{'used': float('nan'), 'minutes': 300, 'reset': 1e300}], 'reasons': 42}):
            state = usage_view({'usage_json': json.dumps(payload),
                                'usage_checked_at': datetime.now(timezone.utc).isoformat()})
            self.assertEqual(state['state'], 'Unknown')
            self.assertEqual(state['windows'], [])

    def test_process_stop_cancels_worker_and_removes_temporary_profile(self):
        code = '''
import tempfile
from pathlib import Path
from unittest.mock import patch
from tests import test_switch
from app.lifecycle import ShutdownController
f = test_switch.SwitchIntegrationTests()
f.setUpClass(); f.setUp()
root = Path(f.temp.name)
def waiting_check(token, stop):
    with tempfile.TemporaryDirectory(prefix='login-', dir=root):
        print('READY', flush=True)
        stop.wait(20)
    return None, 'Cancelled'
with patch('app.usage.fetch_usage', side_effect=waiting_check):
    shutdown = ShutdownController(f.window)
    f.window.show()
    f.window.refresh_usage()
    result = f.app.exec()
    print('CLEAN', not list(root.glob('login-*')), f.window._closing, flush=True)
    shutdown.restore()
f.tearDown()
raise SystemExit(result)
'''
        process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            ready, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(ready, 'Child app failed to start')
            self.assertEqual(process.stdout.readline().strip(), 'READY')
            process.send_signal(signal.SIGTERM)
            output, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('CLEAN True True', output)
        finally:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=2)


if __name__ == '__main__':
    unittest.main()
