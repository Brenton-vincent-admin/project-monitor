import logging
from threading import Event
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QDateTime

from app.codex import get_codex_sessions, get_exhausted_codex_sessions


class ExhaustionMonitor(QThread):
    """Background thread that watches for token exhaustion."""

    exhaustion_detected = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, db, config, check_interval=5):
        super().__init__()
        self.db = db
        self.config = config
        self.check_interval = check_interval
        self._running = False
        self._stop_event = Event()
        self._switching = False
        self._notified_sessions = set()

    def start_monitoring(self):
        self._running = True
        self._stop_event.clear()
        self._notified_sessions = set()
        if not self.isRunning():
            self.start()

    def stop_monitoring(self):
        self._running = False
        self._stop_event.set()

    def run(self):
        while self._running:
            if self._stop_event.wait(self.check_interval) or not self._running:
                break
            try:
                self._check()
            except Exception:
                logging.getLogger(__name__).exception("Exhaustion check failed")
                self.status_update.emit("Monitor check unavailable; retrying without switching accounts")

    def _check(self):
        if self._switching:
            return
        sessions = get_exhausted_codex_sessions()
        if self._switching:
            return
        keys = {(session.pid, session.start_time, session.session_id) for session in sessions}
        new = keys - self._notified_sessions
        if new:
            from app.codex import check_service_connection
            online, message = check_service_connection()
            if not online:
                self.status_update.emit(message)
                return
        self._notified_sessions = keys
        if new:
            self.exhaustion_detected.emit(
                f"{len(sessions)} open Codex chat(s) reached their usage limit"
            )

    def _find_next_account(self):
        return self.db.get_next_available()

    def find_next_account(self):
        """Public wrapper for manual trigger."""
        return self._find_next_account()

    def do_switch(self, acc, mark_current_exhausted=True, resume_sessions=True,
                  full_access=True, exhausted_only=True):
        self._switching = True
        try:
            return self._do_switch(acc, mark_current_exhausted, resume_sessions, full_access, exhausted_only)
        finally:
            self._switching = False

    def _do_switch(self, acc, mark_current_exhausted, resume_sessions, full_access, exhausted_only):
        """Perform the actual switch. Called after user confirms."""
        from app.codex import (
            get_exhaustion_cooldown,
            login_with_token,
            check_service_connection,
            restart_all_codex_sessions,
        )

        online, message = check_service_connection()
        if not online:
            return False, message, 0, ""
        self.status_update.emit(f"Switching to {acc['name']}...")
        sessions = get_codex_sessions() if resume_sessions else []
        active = self.db.get_active_account()
        cooldown_until = None
        cooldown_source = None
        if active and mark_current_exhausted:
            cooldown_until, cooldown_source = get_exhaustion_cooldown(
                self.config.cooldown_seconds
            )
        # Login replaces credentials on success; do not erase the current login first.
        success, msg = login_with_token(acc["token"])

        if success:
            now = QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate)

            if active and cooldown_until:
                self.db.update_account(
                    active["id"],
                    cooldown_until=cooldown_until,
                    last_used_at=now,
                )

            self.db.set_active(acc["id"])
            self.db.update_account(
                acc["id"],
                cooldown_until=None,
                last_used_at=now,
            )

            if resume_sessions:
                restarted, restart_msg = restart_all_codex_sessions(
                    sessions, full_access=full_access, exhausted_only=exhausted_only
                )
            else:
                restarted, restart_msg = 0, "Running chats were not restarted"

            if active and cooldown_until:
                reset = QDateTime.fromString(
                    cooldown_until, Qt.DateFormat.ISODate
                ).toLocalTime().toString("MMM d, h:mm AP")
                restart_msg = (
                    f"Marked {active['name']} used up until {reset} "
                    f"({cooldown_source}). {restart_msg}"
                )
            return True, acc["name"], restarted, restart_msg

        return False, msg, 0, ""


class StatusWorker(QThread):
    """Slow CLI status probes never run in the one-second UI timer."""
    status_ready = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = Event()
        self._pause = False
        self.pids = []

    def stop(self):
        self._stop.set()

    def run(self):
        from app.codex import get_status, get_codex_pids
        while not self._stop.is_set():
            if not self._pause:
                try:
                    self.pids = get_codex_pids()
                    logged_in, message = get_status()
                    self.status_ready.emit(logged_in, message)
                except Exception:
                    logging.getLogger(__name__).exception("Status check failed")
                    self.status_ready.emit(False, "Status unavailable")
            if self._stop.wait(30):
                break


class AccountSwitchWorker(QThread):
    result_ready = pyqtSignal(object)
    status_update = pyqtSignal(str)

    def __init__(self, db_path, config, account, options, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.config = config
        self.account = dict(account)
        self.options = options
        self.result = None

    def run(self):
        from app.db import Database
        db = None
        try:
            # SQLite connections belong to the thread that created them.
            db = Database(self.db_path)
            switcher = ExhaustionMonitor(db, self.config)
            switcher.status_update.connect(self.status_update)
            self.result = switcher.do_switch(self.account, **self.options)
        except Exception:
            logging.getLogger(__name__).exception("Account switch failed")
            self.result = (False, "Account switch failed; see the diagnostic log", 0, "")
        finally:
            if db is not None:
                db.close()
        self.result_ready.emit(self.result)
