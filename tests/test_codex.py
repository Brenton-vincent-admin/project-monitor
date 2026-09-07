import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from app.codex import (
    CodexSession,
    _proc_stat,
    _focus_window,
    _session_id_for_pid,
    _window_ancestor,
    restart_all_codex_sessions,
)


class ProcessDiscoveryTests(unittest.TestCase):
    def test_reads_session_id_from_open_rollout_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = Path(temp_dir)
            fd_dir = proc / "42" / "fd"
            fd_dir.mkdir(parents=True)
            session_id = "12345678-1234-1234-1234-123456789abc"
            (fd_dir / "17").symlink_to(
                f"/home/test/.codex/sessions/rollout-now-{session_id}.jsonl"
            )

            self.assertEqual(_session_id_for_pid(42, proc), session_id)

    def test_reads_parent_and_foreground_process_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = Path(temp_dir)
            pid_dir = proc / "42"
            pid_dir.mkdir()
            # pid, comm, state, ppid, pgrp, session, tty_nr, tpgid
            (pid_dir / "stat").write_text("42 (codex worker) S 30 42 30 34817 42\n")

            self.assertEqual(_proc_stat(42, proc), (30, 42))

    def test_finds_window_process_in_ancestor_chain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = Path(temp_dir)
            for pid, parent in ((42, 30), (30, 20), (20, 1)):
                pid_dir = proc / str(pid)
                pid_dir.mkdir()
                (pid_dir / "stat").write_text(
                    f"{pid} (process) S {parent} {pid} {pid} 34817 {pid}\n"
                )

            self.assertEqual(_window_ancestor(42, {20: "window"}, proc), 20)


class RestartTests(unittest.TestCase):
    def test_focus_uses_hyprland_lua_dispatcher(self):
        with (
            patch(
                "app.codex.subprocess.run",
                return_value=CompletedProcess([], 0, "ok", ""),
            ) as run,
            patch("app.codex._active_window_address", return_value="0xabc"),
            patch("app.codex.time.sleep"),
        ):
            self.assertTrue(_focus_window("0xabc"))

        self.assertEqual(
            run.call_args.args[0],
            [
                "hyprctl",
                "dispatch",
                'hl.dsp.focus({ window = "address:0xabc" })',
            ],
        )

    def test_focus_rejects_untrusted_window_address(self):
        with patch("app.codex.subprocess.run") as run:
            self.assertFalse(_focus_window('0xabc" }) os.execute("bad")'))
        run.assert_not_called()

    def session(self, pid=10, address="0x100", session_id=None):
        return CodexSession(pid, f"/dev/pts/{pid}", "/work with spaces",
                            session_id or "12345678-1234-1234-1234-123456789abc",
                            100, address, 1000, 20, 900)

    def restart(self, sessions, **overrides):
        from contextlib import ExitStack
        defaults = {
            "shutil.which": "/usr/bin/wtype",
            "_active_window_address": "0x999",
            "_same_codex_process": True,
            "_session_exhausted": True,
            "_shell_matches": True,
            "os.kill": None,
            "_wait_for_exit": set(),
            "_wait_for_shell": True,
            "_restore_shell_keyboard": True,
            "_focus_window": True,
            "_type_resume_command": True,
            "_wait_for_resume": True,
        }
        defaults.update(overrides)
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch("app.codex." + name, return_value=value))
                     for name, value in defaults.items()}
            result = restart_all_codex_sessions(sessions)
        return result, mocks

    def test_restarts_six_exact_chats_with_full_access(self):
        import shlex
        sessions = [self.session(pid=i, address=f"0x{i}",
                    session_id=f"12345678-1234-1234-1234-{i:012d}") for i in range(10, 16)]
        (count, summary), mocks = self.restart(sessions)
        self.assertEqual(count, 6)
        for call, session in zip(mocks["_type_resume_command"].call_args_list, sessions):
            self.assertEqual(shlex.split(call.args[0]), [
                "codex", "resume", session.session_id, "--cd", session.cwd,
                "--sandbox", "danger-full-access", "--ask-for-approval", "never"])
        self.assertEqual(mocks["_wait_for_resume"].call_count, 6)
        self.assertEqual(mocks["_restore_shell_keyboard"].call_count, 6)
        mocks["_focus_window"].assert_called_with("0x999")

    def test_leaves_shared_windows_alone(self):
        sessions = [self.session(), self.session(11, "0x200"), self.session(12, "0x200")]
        (count, summary), mocks = self.restart(sessions)
        self.assertEqual(count, 1)
        mocks["os.kill"].assert_called_once()
        self.assertIn("left 2 unidentified or ambiguous session(s) untouched", summary)

    def test_unknown_chat_never_gets_replaced_with_blank_chat(self):
        from dataclasses import replace
        (count, _), mocks = self.restart([replace(self.session(), session_id=None)])
        self.assertEqual(count, 0)
        mocks["os.kill"].assert_not_called()
        mocks["_type_resume_command"].assert_not_called()

    def test_stale_process_is_not_restarted(self):
        (_, _), mocks = self.restart([self.session()], _same_codex_process=False)
        mocks["os.kill"].assert_not_called()
        mocks["_type_resume_command"].assert_not_called()

    def test_missing_keyboard_tool_never_stops_a_session(self):
        (count, summary), mocks = self.restart([self.session()], **{"shutil.which": None})
        self.assertEqual(count, 0)
        self.assertIn("no sessions were stopped", summary)
        mocks["os.kill"].assert_not_called()

    def test_failed_focus_never_stops_a_session(self):
        (count, _), mocks = self.restart([self.session()], _focus_window=False)
        self.assertEqual(count, 0)
        mocks["os.kill"].assert_not_called()

    def test_does_not_type_until_original_shell_returns(self):
        (count, summary), mocks = self.restart([self.session()], _wait_for_shell=False)
        self.assertEqual(count, 0)
        mocks["_type_resume_command"].assert_not_called()
        self.assertIn("Manual recovery commands", summary)

    def test_typing_command_is_not_counted_as_success(self):
        (count, summary), mocks = self.restart([self.session()], _wait_for_resume=False)
        self.assertEqual(count, 0)
        self.assertIn("could not restart 1", summary)

    def test_keyboard_reset_failure_prevents_garbled_input(self):
        (count, _), mocks = self.restart([self.session()], _restore_shell_keyboard=False)
        self.assertEqual(count, 0)
        mocks['_type_resume_command'].assert_not_called()

    def test_keyboard_reset_only_writes_to_original_foreground_shell(self):
        from app.codex import _restore_shell_keyboard
        with (patch('app.codex._shell_matches', return_value=False),
              patch('app.codex.os.open') as opened):
            self.assertFalse(_restore_shell_keyboard(self.session()))
            opened.assert_not_called()

    def test_keyboard_reset_emits_protocol_reset_to_terminal_output(self):
        import os
        import pty
        from dataclasses import replace
        from app.codex import _restore_shell_keyboard
        master, slave = pty.openpty()
        try:
            session = replace(self.session(), tty=os.ttyname(slave))
            with patch('app.codex._shell_matches', return_value=True):
                self.assertTrue(_restore_shell_keyboard(session))
            self.assertEqual(os.read(master, 32), b'\x1b[=0u')
        finally:
            os.close(master)
            os.close(slave)

    def test_permission_choice_can_use_codex_defaults(self):
        from app.codex import _resume_command
        command = _resume_command(self.session(), full_access=False)
        self.assertNotIn("danger-full-access", command)
        self.assertNotIn("never", command)

    def test_resume_command_rejects_invalid_id_and_multiline_directory(self):
        from app.codex import _resume_command
        from dataclasses import replace
        for session in [replace(self.session(), session_id="$(bad)"),
                        replace(self.session(), cwd="/work\nmalicious")]:
            self.assertIsNone(_resume_command(session))


if __name__ == "__main__":
    unittest.main()
