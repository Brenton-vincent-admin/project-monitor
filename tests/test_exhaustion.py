import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.codex import _rollout_exhausted, check_exhaustion
from app.monitor import ExhaustionMonitor


class ExhaustionTests(unittest.TestCase):
    def event(self, used=100, reset=5000, reached=None, timestamp='1970-01-01T00:30:00Z', credits=False):
        return {'timestamp': timestamp, 'type': 'event_msg', 'payload': {
            'type': 'token_count', 'rate_limits': {
                'primary': {'used_percent': used, 'resets_at': reset},
                'credits': {'has_credits': credits, 'unlimited': False},
                'rate_limit_reached_type': reached}}}

    def exhausted(self, events, started=1000):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rollout.jsonl'
            path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
            return _rollout_exhausted(path, started, now=2000)

    def test_current_quota_exhaustion(self):
        self.assertTrue(self.exhausted([self.event()]))

    def test_large_conversation_entry_cannot_hide_exhaustion(self):
        oversized = {'type': 'event_msg', 'payload': {
            'type': 'agent_message', 'message': 'x' * (3 * 1024 * 1024)}}
        self.assertTrue(self.exhausted([self.event(reached='workspace_owner_credits_depleted'), oversized]))
        self.assertFalse(self.exhausted([self.event(used=5), oversized]))
        self.assertFalse(self.exhausted([self.event(), oversized, self.event(used=5)]))

    def test_cached_quota_updates_on_append_and_reset_time(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rollout.jsonl'
            path.write_text(json.dumps(self.event()) + '\n')
            self.assertTrue(_rollout_exhausted(path, 1000, now=2000))
            self.assertFalse(_rollout_exhausted(path, 1000, now=5001))
            with path.open('a') as stream:
                stream.write(json.dumps(self.event(used=5)) + '\n')
            self.assertFalse(_rollout_exhausted(path, 1000, now=2000))

    def test_explicit_credit_exhaustion_without_percentage(self):
        event = self.event(used=5, reached='workspace_member_credits_depleted')
        event['payload']['rate_limits']['primary'] = None
        self.assertTrue(self.exhausted([event]))

    def test_healthy_chat_is_excluded(self):
        self.assertFalse(self.exhausted([self.event(used=99)]))

    def test_latest_healthy_update_clears_old_exhaustion(self):
        self.assertFalse(self.exhausted([self.event(), self.event(used=5)]))

    def test_exhaustion_from_previous_process_is_excluded(self):
        self.assertFalse(self.exhausted([self.event()], started=1900))

    def test_elapsed_quota_reset_is_excluded(self):
        self.assertFalse(self.exhausted([self.event(reset=1999)]))

    def test_credit_fallback_does_not_count_as_exhausted(self):
        self.assertFalse(self.exhausted([self.event(credits=True)]))

    def test_conversation_text_cannot_trigger_exhaustion(self):
        self.assertFalse(self.exhausted([{'type': 'response_item', 'payload': {
            'type': 'message', 'content': 'usage limit reached 100%'}}]))

    def test_closed_chats_do_not_trigger_monitor(self):
        monitor = ExhaustionMonitor(None, None)
        monitor._was_active = True
        seen = []
        monitor.exhaustion_detected.connect(seen.append)
        with patch('app.monitor.get_exhausted_codex_sessions', return_value=[]):
            monitor._check()
        self.assertEqual(seen, [])
        with patch('app.codex.get_exhausted_codex_sessions', return_value=[]):
            self.assertFalse(check_exhaustion()[0])

    def test_monitor_reports_each_exhausted_process_once(self):
        from app.codex import CodexSession
        session = CodexSession(10, '/dev/pts/1', '/work', 'id', 20, '0x100', 1000)
        monitor = ExhaustionMonitor(None, None)
        seen = []
        monitor.exhaustion_detected.connect(seen.append)
        with (patch('app.monitor.get_exhausted_codex_sessions', return_value=[session]),
              patch('app.codex.check_service_connection', return_value=(True, 'online'))):
            monitor._check()
            monitor._check()
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
