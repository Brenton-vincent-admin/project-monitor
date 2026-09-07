import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from tests import test_switch
from app.db import Database
from app.usage import fetch_usage, normalize_usage, usage_view


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def snapshot(used=10, weekly=20, now=None):
    now = time.time() if now is None else now
    return normalize_usage({'rateLimits': {'primary': {
        'usedPercent': used, 'windowDurationMins': 300, 'resetsAt': now + 3600},
        'secondary': {'usedPercent': weekly, 'windowDurationMins': 10080, 'resetsAt': now + 86400}}})


class UsageTests(unittest.TestCase):
    def account(self, used=10, weekly=20, **kwargs):
        return dict(usage_json=json.dumps(snapshot(used, weekly, 2000)),
                    usage_checked_at=stamp(2000), **kwargs)

    def test_readiness_uses_both_windows(self):
        self.assertEqual(usage_view(self.account(), 2000)['state'], 'Ready')
        self.assertEqual(usage_view(self.account(weekly=80), 2000)['state'], 'Nearly used up')
        self.assertEqual(usage_view(self.account(weekly=100), 2000)['state'], 'Limit reached')

    def test_unknown_stale_and_failed_checks_are_not_ready(self):
        self.assertEqual(usage_view({}, 2000)['state'], 'Not checked')
        self.assertEqual(usage_view(self.account(), 2700)['state'], 'Stale')
        self.assertEqual(usage_view(self.account(usage_error='Offline'), 2000)['state'], 'Check failed')

    def test_passed_reset_needs_recheck_but_does_not_hide_weekly_limit(self):
        account = self.account()
        data = json.loads(account['usage_json'])
        data['windows'][0]['reset'] = 1999
        account['usage_json'] = json.dumps(data)
        self.assertEqual(usage_view(account, 2000)['state'], 'Check reset')
        data['windows'][1]['used'] = 100
        account['usage_json'] = json.dumps(data)
        self.assertEqual(usage_view(account, 2000)['state'], 'Limit reached')

    def test_credit_depletion_does_not_invent_reset_time(self):
        account = self.account()
        data = json.loads(account['usage_json'])
        data['reasons'] = ['workspace_owner_credits_depleted']
        account['usage_json'] = json.dumps(data)
        view = usage_view(account, 2000)
        self.assertTrue(view['blocked'])
        self.assertEqual(view['reset'], 0)

    def test_paid_credit_fallback_keeps_account_usable(self):
        data = normalize_usage({'rateLimits': {'credits': {'hasCredits': True},
            'primary': {'usedPercent': 100, 'windowDurationMins': 300, 'resetsAt': 5000}}})
        view = usage_view(dict(usage_json=json.dumps(data), usage_checked_at=stamp(2000)), 2000)
        self.assertFalse(view['blocked'])
        self.assertEqual(view['state'], 'Nearly used up')

    def test_local_exhaustion_newer_than_usage_wins(self):
        account = self.account(cooldown_until=stamp(5000), last_used_at=stamp(2010))
        self.assertEqual(usage_view(account, 2020)['state'], 'Cooling down')
        account['usage_checked_at'] = stamp(2020)
        self.assertEqual(usage_view(account, 2020)['state'], 'Ready')

    def test_malformed_usage_is_unknown_not_zero_percent(self):
        data = normalize_usage({'rateLimits': {'primary': {'usedPercent': 'bad'}}})
        self.assertEqual(data['windows'], [])
        self.assertEqual(usage_view(dict(usage_json=json.dumps(data), usage_checked_at=stamp(2000)), 2000)['state'], 'Unknown')

    def test_rotation_prefers_capacity_and_skips_known_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'accounts.db')
            unknown = db.add_account('Unknown', 'fake1')
            nearly = db.add_account('Nearly', 'fake2')
            ready = db.add_account('Ready', 'fake3')
            blocked = db.add_account('Blocked', 'fake4')
            for account, used in ((nearly, 90), (ready, 10), (blocked, 100)):
                db.update_account(account, usage_json=json.dumps(snapshot(used)), usage_checked_at=stamp(time.time()))
            self.assertEqual(db.get_next_available()['id'], ready)
            db.set_active(ready)
            self.assertEqual(db.get_next_available()['id'], nearly)
            db.update_account(nearly, in_rotation=0)
            self.assertEqual(db.get_next_available()['id'], unknown)
            db.close()

    def test_replacing_token_invalidates_cached_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'accounts.db')
            account = db.add_account('Test', 'old')
            db.update_account(account, usage_json=json.dumps(snapshot()), usage_checked_at=stamp(time.time()))
            db.update_account(account, token='new')
            self.assertIsNone(db.get_account(account)['usage_json'])
            db.close()

    def test_fetch_uses_disposable_profile_and_only_reads_limits(self):
        # Run real child processes against a fake CLI boundary. Verify profile
        # isolation, stdin credentials, RPC allowlist, and cleanup.
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'fake_cli.py'
            report = Path(directory) / 'calls.jsonl'
            fake.write_text('''import json, os, sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
with open(os.environ['PM_TEST_REPORT'], 'a') as f:
    f.write(json.dumps({'home': str(home), 'command': sys.argv[1:],
        'external_token': 'CODEX_ACCESS_TOKEN' in os.environ,
        'file_store': '"file"' in (home / 'config.toml').read_text()}) + '\\n')
if sys.argv[1] == 'login':
    assert sys.stdin.read() == 'test-access-token'
    (home / 'auth.json').write_text('{}')
else:
    for line in sys.stdin:
        request = json.loads(line)
        assert request['method'] in ('initialize', 'initialized', 'account/rateLimits/read')
        if request['method'] == 'initialize':
            print(json.dumps({'id': 0, 'result': {}}), flush=True)
        elif request['method'] == 'account/rateLimits/read':
            print(json.dumps({'id': 1, 'result': {'rateLimits': {
                'primary': {'usedPercent': 37, 'windowDurationMins': 300, 'resetsAt': 2000000000}}}}), flush=True)
''')
            real_popen = subprocess.Popen
            def launch(args, **kwargs):
                return real_popen([sys.executable, str(fake)] + args[1:], **kwargs)
            with (patch.dict(os.environ, {'PM_TEST_REPORT': str(report), 'CODEX_ACCESS_TOKEN': 'wrong-account'}),
                  patch('app.usage.subprocess.Popen', side_effect=launch)):
                result, error = fetch_usage('test-access-token')
            self.assertIsNone(error)
            self.assertEqual(result['windows'][0]['used'], 37)
            calls = [json.loads(line) for line in report.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c['file_store'] and not c['external_token'] for c in calls))
            self.assertTrue(all(not Path(c['home']).exists() for c in calls))


class UsageUiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_switch.SwitchIntegrationTests()
        self.fixture.setUpClass()
        self.fixture.setUp()

    def tearDown(self):
        worker = self.fixture.window._usage_worker
        if worker is not None:
            worker.stop(); worker.wait()
            self.fixture.app.processEvents()
        self.fixture.tearDown()

    def test_background_refresh_updates_rows_without_switching_or_restarting(self):
        f = self.fixture
        with (patch('app.usage.fetch_usage', return_value=(snapshot(85), None)),
              patch('app.codex.login_with_token') as login,
              patch('app.codex.restart_all_codex_sessions') as restart):
            f.window.refresh_usage()
            deadline = time.monotonic() + 2
            while f.window._usage_worker is not None and time.monotonic() < deadline:
                f.app.processEvents(); time.sleep(.01)
            self.assertIsNone(f.window._usage_worker)
            self.assertEqual(f.db.get_active_account()['id'], f.old)
            self.assertIsNone(f.db.get_account(f.old)['cooldown_until'])
            self.assertIn('15% left', f.window.table.item(0, 1).text())
            self.assertEqual(f.window.table.item(1, 2).text(), 'Nearly used up')
            login.assert_not_called(); restart.assert_not_called()

    def test_failed_check_keeps_previous_values_and_token_change_ignores_late_result(self):
        f = self.fixture
        checked = stamp(time.time())
        f.window._usage_received(f.new, 'fake-new', snapshot(), None, checked)
        previous = f.db.get_account(f.new)['usage_json']
        f.window._usage_received(f.new, 'fake-new', None, 'Offline', checked)
        self.assertEqual(f.db.get_account(f.new)['usage_json'], previous)
        self.assertEqual(f.window.table.item(1, 2).text(), 'Check failed')
        f.db.update_account(f.new, token='replacement')
        f.window._usage_received(f.new, 'fake-new', snapshot(), None, checked)
        self.assertIsNone(f.db.get_account(f.new)['usage_json'])

    def test_close_cancels_usage_before_closing_database(self):
        f = self.fixture
        def pending(token, stop):
            stop.wait(2)
            return None, 'Cancelled'
        with patch('app.usage.fetch_usage', side_effect=pending):
            f.window.refresh_usage()
            worker = f.window._usage_worker
            before = time.monotonic()
            f.window.close()
            self.assertLess(time.monotonic() - before, 1)
            self.assertFalse(worker.isRunning())
            self.assertFalse(f.window.usage_timer.isActive())
            f.window._usage_received(f.new, 'fake-new', snapshot(), None, stamp(time.time()))

    def test_small_charts_have_separate_tooltips_and_preserve_row_height(self):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QHelpEvent
        from PyQt6.QtWidgets import QStyleOptionViewItem
        f = self.fixture
        f.window._usage_received(f.new, 'fake-new', snapshot(25, 90), None, stamp(time.time() - 245))
        f.window.show(); f.app.processEvents()
        item = f.window.table.item(1, 1)
        charts = item.data(Qt.ItemDataRole.UserRole)
        self.assertEqual([c['label'] for c in charts], ['5H', '7D'])
        self.assertEqual([c['remaining'] for c in charts], [75, 10])
        self.assertEqual(f.window.table.rowHeight(1), 72)
        index = f.window.table.indexFromItem(item)
        option = QStyleOptionViewItem()
        option.rect = f.window.table.visualRect(index)
        delegate = f.window.table.itemDelegateForColumn(1)
        for position, expected in zip(delegate.chart_rects(option.rect), ('75% left', '10% left')):
            point = position.center().toPoint()
            event = QHelpEvent(QEvent.Type.ToolTip, point, point)
            with patch('app.usage_charts.QToolTip.showText') as show:
                self.assertTrue(delegate.helpEvent(event, f.window.table, option, index))
            self.assertIn(expected, show.call_args.args[1])
            self.assertIn('Checked 4m ago', show.call_args.args[1])

    def test_account_menu_and_selection_action(self):
        window = self.fixture.window
        self.assertEqual([a.text() for a in window.account_menu.actions() if not a.isSeparator()],
                         ['Import CSV…', 'Add account…', 'Remove selected account…'])
        self.assertFalse(window.switch_action.isVisible())
        self.assertFalse(window.remove_action.isEnabled())
        window.table.selectRow(1)
        self.assertTrue(window.switch_action.isVisible())
        self.assertTrue(window.btn_switch.isEnabled())
        self.assertTrue(window.remove_action.isEnabled())

    def test_chart_colors_progress_from_green_to_red(self):
        from app.usage_charts import usage_color
        from app.theme import C
        self.assertEqual(usage_color(100).name(), C['green'])
        self.assertEqual(usage_color(50).name(), C['orange'])
        self.assertEqual(usage_color(0).name(), C['red'])
        self.assertNotEqual(usage_color(75), usage_color(25))


if __name__ == '__main__':
    unittest.main()
