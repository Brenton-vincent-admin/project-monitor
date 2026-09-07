import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORMTHEME'] = ''
os.environ['QT_STYLE_OVERRIDE'] = 'Fusion'

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.db import Database
from app.monitor import ExhaustionMonitor
from config import ConfigManager
from ui import MainWindow


class SwitchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Database(root / 'monitor.db')
        self.config = ConfigManager(root / 'config.json')
        self.old = self.db.add_account('Old', 'fake-old')
        self.new = self.db.add_account('New', 'fake-new')
        self.db.set_active(self.old)
        with patch.object(MainWindow, '_setup_tray', lambda window: setattr(window, 'tray_icon', None)):
            self.window = MainWindow(self.db, self.config)
        self.window.timer.stop()

    def tearDown(self):
        self.window.monitor.stop_monitoring()
        self.window.monitor.wait()
        if getattr(self.window, '_switch_worker', None):
            self.window._switch_worker.wait(3000)
            self.app.processEvents()
        self.window.status_worker.stop()
        self.window.status_worker.wait()
        self.window._closing = True
        self.window.deleteLater()
        self.db.close()
        self.temp.cleanup()

    def wait_for_switch(self):
        deadline = time.monotonic() + 3
        while self.window._switch_in_progress and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window._switch_in_progress)

    def switch(self, next_available=False, login_success=True):
        with (
            patch('ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes),
            patch('ui.QMessageBox.warning'),
            patch('app.monitor.get_codex_sessions', return_value=['snapshot']),
            patch('app.codex.logout'),
            patch('app.codex.check_service_connection', return_value=(True, 'online')),
            patch('app.codex.login_with_token', return_value=(login_success, 'test login')),
            patch('app.codex.get_exhaustion_cooldown', return_value=('2099-01-01T00:00:00Z', 'test reset')) as cooldown,
            patch('app.codex.restart_all_codex_sessions', return_value=(6, 'Restarted 6 session(s)')) as restart,
        ):
            if next_available:
                self.window.switch_to_next_available()
            else:
                self.window.select_account(self.new)
            self.wait_for_switch()
        return restart, cooldown

    def test_manual_selected_account_does_not_restart_chats(self):
        restart, cooldown = self.switch()
        restart.assert_not_called()
        cooldown.assert_not_called()
        self.assertEqual(self.db.get_active_account()['id'], self.new)
        self.assertIsNone(self.db.get_account(self.old)['cooldown_until'])

    def test_semi_auto_preserves_cooldown_and_resumes_only_exhausted_chats(self):
        self.window.rotation_mode.setCurrentIndex(1)
        restart, cooldown = self.switch(next_available=True)
        restart.assert_called_once_with(['snapshot'], full_access=True, exhausted_only=True)
        self.assertEqual(self.db.get_account(self.old)['cooldown_until'], '2099-01-01T00:00:00Z')

    def test_failed_login_never_stops_chats_or_changes_active_record(self):
        restart, _ = self.switch(login_success=False)
        restart.assert_not_called()
        self.assertEqual(self.db.get_active_account()['id'], self.old)
        self.assertFalse(self.window.monitor._switching)

    def test_full_access_choice_is_passed_through(self):
        self.window.rotation_mode.setCurrentIndex(1)
        self.window.full_access.setChecked(False)
        restart, _ = self.switch()
        restart.assert_called_once_with(['snapshot'], full_access=False, exhausted_only=True)

    def enable_automatic(self):
        with patch.object(self.window.monitor, 'start_monitoring'):
            self.window.rotation_mode.setCurrentIndex(2)

    def test_manual_rotation_needs_no_confirmation(self):
        with (patch('ui.QMessageBox.question') as question,
              patch.object(self.window, '_confirm_and_switch') as switch):
            self.window.switch_to_next_available()
        question.assert_not_called()
        self.assertTrue(switch.call_args.kwargs['exhausted_only'])

    def test_full_auto_rotate_button_resumes_only_exhausted_chats(self):
        self.enable_automatic()
        restart, _ = self.switch(next_available=True)
        restart.assert_called_once_with(['snapshot'], full_access=True, exhausted_only=True)

    def test_automatic_switches_without_asking_and_only_resumes_exhausted(self):
        self.enable_automatic()
        with (patch('app.codex.get_exhausted_codex_sessions', return_value=['exhausted']),
              patch('ui.QMessageBox.question') as question,
              patch.object(self.window, '_confirm_and_switch') as switch):
            self.window._on_exhaustion_detected('quota depleted')
        question.assert_not_called()
        self.assertTrue(switch.call_args.kwargs['exhausted_only'])
        self.assertTrue(switch.call_args.kwargs['automatic'])
        self.assertEqual(self.config.get('rotation_mode'), 'full_auto')

    def test_manual_mode_ignores_queued_exhaustion(self):
        with patch.object(self.window, '_confirm_and_switch') as switch:
            self.window._on_exhaustion_detected('old notification')
        switch.assert_not_called()

    def test_automatic_rechecks_exhaustion_before_switching(self):
        self.enable_automatic()
        with (patch('app.codex.get_exhausted_codex_sessions', return_value=[]),
              patch.object(self.window, '_confirm_and_switch') as switch):
            self.window._on_exhaustion_detected('stale notification')
        switch.assert_not_called()

    def test_automatic_pauses_when_no_accounts_available(self):
        self.db.remove_account(self.new)
        self.enable_automatic()
        with (patch('app.codex.get_exhausted_codex_sessions', return_value=['exhausted']),
              patch.object(self.window, '_confirm_and_switch') as switch):
            self.window._on_exhaustion_detected('quota depleted')
        switch.assert_not_called()
        self.assertFalse(self.window._monitor_active)
        self.assertEqual(self.config.get('rotation_mode'), 'manual')

    def test_automatic_pauses_after_login_failure(self):
        self.enable_automatic()
        with (patch.object(ExhaustionMonitor, 'do_switch', return_value=(False, 'login failed', 0, '')),
              patch('ui.QMessageBox.warning')):
            self.window._confirm_and_switch(self.db.get_account(self.new), automatic=True)
            self.wait_for_switch()
        self.assertFalse(self.window._monitor_active)

    def test_automatic_pauses_after_partial_resume_failure(self):
        self.enable_automatic()
        with (patch.object(ExhaustionMonitor, 'do_switch', return_value=(True, 'New', 2, 'Restarted 2; could not restart 1')),
              patch('ui.QMessageBox.warning')):
            self.window._confirm_and_switch(self.db.get_account(self.new), automatic=True)
            self.wait_for_switch()
        self.assertFalse(self.window._monitor_active)

    def test_saved_automatic_mode_starts_monitor_on_launch(self):
        self.config.set('rotation_mode', 'automatic')
        with (patch.object(ExhaustionMonitor, 'start_monitoring') as start,
              patch.object(MainWindow, '_setup_tray', lambda window: setattr(window, 'tray_icon', None))):
            window = MainWindow(self.db, self.config)
        self.assertTrue(window._monitor_active)
        start.assert_called_once()
        window.timer.stop()
        window.deleteLater()

    def test_monitor_stops_without_waiting_for_poll_interval(self):
        monitor = ExhaustionMonitor(None, None, check_interval=30)
        monitor.start_monitoring()
        monitor.stop_monitoring()
        self.assertTrue(monitor.wait(1000))


if __name__ == '__main__':
    unittest.main()
