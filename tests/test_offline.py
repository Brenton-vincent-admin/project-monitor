import subprocess
import time
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QTimer

from tests import test_switch
from app.codex import CodexSession, check_service_connection, get_status
from app.monitor import ExhaustionMonitor, StatusWorker


class OfflineTests(unittest.TestCase):
    def test_reachable_service_that_rejects_head_does_not_block_rotation(self):
        # Reproduce the live endpoint: HEAD returns 405; GET returns 401.
        def endpoint(command, **kwargs):
            code = '405' if '--head' in command else '401'
            return subprocess.CompletedProcess(command, 0, code, '')

        with patch('app.codex.subprocess.run', side_effect=endpoint):
            self.assertTrue(check_service_connection()[0])

    def test_login_status_timeout_is_unavailable_not_an_exception(self):
        with patch('app.codex.subprocess.run', side_effect=subprocess.TimeoutExpired(['codex', 'login', 'status'], 3)):
            logged_in, message = get_status()
        self.assertFalse(logged_in)
        self.assertIn('unavailable', message)

    def test_connection_timeout_prevents_rotation(self):
        with patch('app.codex.subprocess.run', side_effect=subprocess.TimeoutExpired(['curl'], 5)):
            self.assertFalse(check_service_connection()[0])

    def test_service_errors_do_not_count_as_reachable(self):
        for code in ('000', '429', '500', '503'):
            with patch('app.codex.subprocess.run', return_value=subprocess.CompletedProcess([], 0, code, '')):
                self.assertFalse(check_service_connection()[0])

    def test_offline_all_modes_leave_login_database_and_chats_untouched(self):
        for mode in (0, 1, 2):
            fixture = test_switch.SwitchIntegrationTests()
            fixture.setUpClass(); fixture.setUp()
            try:
                with (
                    patch.object(fixture.window.monitor, 'start_monitoring'),
                    patch('app.codex.check_service_connection', return_value=(False, 'Offline or Codex service unavailable — accounts and chats were left untouched')),
                    patch('app.codex.login_with_token') as login,
                    patch('app.codex.logout') as logout,
                    patch('app.codex.restart_all_codex_sessions') as restart,
                    patch('app.codex.get_exhaustion_cooldown') as cooldown,
                    patch('ui.QMessageBox.warning'),
                ):
                    fixture.window.rotation_mode.setCurrentIndex(mode)
                    fixture.window._confirm_and_switch(fixture.db.get_account(fixture.new), automatic=mode == 2)
                    fixture.wait_for_switch()
                    login.assert_not_called(); logout.assert_not_called()
                    restart.assert_not_called(); cooldown.assert_not_called()
                    self.assertEqual(fixture.db.get_active_account()['id'], fixture.old)
                    self.assertIsNone(fixture.db.get_account(fixture.old)['cooldown_until'])
                    if mode == 2:
                        self.assertTrue(fixture.window._monitor_active)
            finally:
                fixture.tearDown()

    def test_full_auto_waits_offline_then_retries_same_exhausted_session(self):
        monitor = ExhaustionMonitor(None, None)
        session = CodexSession(10, '/dev/pts/1', '/work', 'id', 20, '0x100', 1000)
        seen = []
        monitor.exhaustion_detected.connect(seen.append)
        with (patch('app.monitor.get_exhausted_codex_sessions', return_value=[session]),
              patch('app.codex.check_service_connection', side_effect=[(False, 'Offline'), (False, 'Offline'), (True, 'Online')])):
            monitor._check(); monitor._check()
            self.assertEqual(seen, [])
            monitor._check()
        self.assertEqual(len(seen), 1)

    def test_manual_rotate_button_never_calls_restart(self):
        fixture = test_switch.SwitchIntegrationTests()
        fixture.setUpClass(); fixture.setUp()
        try:
            restart, _ = fixture.switch(next_available=True)
            restart.assert_not_called()
            self.assertEqual(fixture.db.get_active_account()['id'], fixture.new)
        finally:
            fixture.tearDown()

    def test_slow_status_probe_does_not_block_ui_timer(self):
        fixture = test_switch.SwitchIntegrationTests()
        fixture.setUpClass(); fixture.setUp()
        worker = StatusWorker()
        beats = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: beats.append(1))
        results = []
        worker.status_ready.connect(lambda *value: results.append(value))
        def slow_status():
            time.sleep(.2)
            return False, 'Status unavailable'
        try:
            with (patch('app.codex.get_status', side_effect=slow_status),
                  patch('app.codex.get_codex_pids', return_value=[])):
                timer.start(); worker.start()
                deadline = time.monotonic() + 1
                while not results and time.monotonic() < deadline:
                    fixture.app.processEvents(); time.sleep(.005)
                self.assertGreater(len(beats), 10)
                self.assertEqual(results, [(False, 'Status unavailable')])
        finally:
            timer.stop(); worker.stop(); worker.wait(1000)
            fixture.tearDown()

    def test_unexpected_ui_timer_error_is_contained(self):
        fixture = test_switch.SwitchIntegrationTests()
        fixture.setUpClass(); fixture.setUp()
        try:
            with (patch.object(fixture.db, 'get_all_accounts', side_effect=RuntimeError('test error')),
                  patch('ui.logging.getLogger')):
                fixture.window._safe_tick()
            self.assertIn('paused after an error', fixture.window.statusbar.currentMessage())
            self.assertFalse(fixture.window.timer.isActive())
        finally:
            fixture.tearDown()

    def test_close_stops_timer_before_database_and_ignores_late_tick(self):
        fixture = test_switch.SwitchIntegrationTests()
        fixture.setUpClass(); fixture.setUp()
        try:
            fixture.window.timer.start()
            original_close = fixture.db.close
            def checked_close():
                self.assertFalse(fixture.window.timer.isActive())
                self.assertTrue(fixture.window._closing)
                original_close()
            with patch.object(fixture.db, 'close', side_effect=checked_close):
                fixture.window.close()
            # Reproduce the crashed callback after DB closure: it must not query.
            with patch.object(fixture.db, 'get_all_accounts') as read:
                fixture.window._safe_tick()
                read.assert_not_called()
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
