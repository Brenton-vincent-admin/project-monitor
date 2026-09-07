"""Exercise the real Qt monitor-to-UI-to-switch-to-resume chain.

Only OS/CLI boundaries are simulated; no real credentials or chats are touched.
"""
import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Configure Qt for isolated, headless tests before creating the application.
from tests import test_switch
from app.codex import CodexSession, _rollout_exhausted


class AutomaticFlowTests(unittest.TestCase):
    def test_timer_detects_rotates_and_resumes_only_exhausted_chats_once(self):
        self.check_rotation_flow(2)

    def test_semi_auto_click_resumes_six_exhausted_and_leaves_two_healthy(self):
        self.check_rotation_flow(1)

    def check_rotation_flow(self, mode):
        fixture = test_switch.SwitchIntegrationTests()
        fixture.setUpClass()
        fixture.setUp()
        window = fixture.window
        sessions = [CodexSession(
            i, f'/dev/pts/{i}', '/test project',
            f'12345678-1234-1234-1234-{i:012d}', i + 100,
            f'0x{i}', 1000, i + 200, 900,
        ) for i in range(10, 18)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            started_at = time.time() - 1

            def quota(session, used):
                (root / str(session.pid)).write_text(json.dumps({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'type': 'event_msg', 'payload': {'type': 'token_count',
                        'rate_limits': {'primary': {
                            'used_percent': used, 'resets_at': time.time() + 3600},
                            'credits': {'has_credits': False}}}}) + '\n')

            for index, session in enumerate(sessions):
                quota(session, 100 if index < 6 else 10)

            def resumed(session):
                quota(session, 0)
                return True

            try:
                with ExitStack() as stack:
                    def mock(name, **kwargs):
                        return stack.enter_context(patch(name, **kwargs))
                    mock('app.codex.get_codex_sessions', return_value=sessions)
                    mock('app.monitor.get_codex_sessions', return_value=sessions)
                    mock('app.codex._session_exhausted', side_effect=lambda s:
                         _rollout_exhausted(root / str(s.pid), started_at))
                    mock('app.codex._same_codex_process', return_value=True)
                    mock('app.codex._shell_matches', return_value=True)
                    mock('app.codex.shutil.which', return_value='/usr/bin/wtype')
                    mock('app.codex._active_window_address', return_value='0x999')
                    mock('app.codex._focus_window', return_value=True)
                    kill = mock('app.codex.os.kill')
                    mock('app.codex._wait_for_exit', return_value=set())
                    mock('app.codex._wait_for_shell', return_value=True)
                    mock('app.codex._restore_shell_keyboard', return_value=True)
                    typed = mock('app.codex._type_resume_command', return_value=True)
                    mock('app.codex._wait_for_resume', side_effect=resumed)
                    mock('app.codex.check_service_connection', return_value=(True, 'online'))
                    logout = mock('app.codex.logout', return_value=(True, 'logged out'))
                    login = mock('app.codex.login_with_token', return_value=(True, 'logged in'))
                    mock('app.codex.get_exhaustion_cooldown', return_value=(
                        '2099-01-01T00:00:00Z', 'test reset'))
                    question = mock('ui.QMessageBox.question')
                    warning = mock('ui.QMessageBox.warning')
                    # Faster clock for this test; production uses five seconds.
                    window.monitor.check_interval = .05
                    window.rotation_mode.setCurrentIndex(mode)
                    if mode == 1:
                        window.switch_to_next_available()
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and typed.call_count < 6:
                        fixture.app.processEvents()
                        time.sleep(.01)
                    # Let further polls run to detect accidental rotation loops.
                    until = time.monotonic() + .25
                    while time.monotonic() < until:
                        fixture.app.processEvents()
                        time.sleep(.01)
                    window.monitor.stop_monitoring()
                    self.assertTrue(window.monitor.wait(1000))
                    self.assertEqual(typed.call_count, 6)
                    self.assertEqual([c.args[0] for c in kill.call_args_list], list(range(10, 16)))
                    login.assert_called_once_with('fake-new')
                    logout.assert_not_called()
                    question.assert_not_called()
                    warning.assert_not_called()
                    self.assertEqual(fixture.db.get_active_account()['id'], fixture.new)
                    self.assertEqual(fixture.db.get_account(fixture.old)['cooldown_until'],
                                     '2099-01-01T00:00:00Z')
                    self.assertEqual(window._monitor_active, mode == 2)
                    self.assertIn('Restarted 6', window.statusbar.currentMessage())
                    for call, session in zip(typed.call_args_list, sessions):
                        self.assertIn(session.session_id, call.args[0])
                        self.assertIn('--sandbox danger-full-access --ask-for-approval never', call.args[0])
            finally:
                fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
