import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from app.db import Database
from config import ConfigManager
from app.lifecycle import ShutdownController
from ui import MainWindow, DB_PATH, CONFIG_PATH


def main():
    log_dir = Path.home() / ".local" / "state" / "project-monitor"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = log_dir / "app.log"
    handler = RotatingFileHandler(log_path, maxBytes=256_000, backupCount=3)
    log_path.chmod(0o600)
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def report_exception(exc_type, exc_value, tb):
        # PyQt aborts by default for an unhandled slot exception. Keep diagnostics
        # without dumping exception values that may contain account information.
        logging.error("Unhandled %s\n%s", exc_type.__name__, "".join(traceback.format_tb(tb)))
        if "window" in locals_for_errors:
            window = locals_for_errors["window"]
            window.timer.stop()
            window.monitor.stop_monitoring()
            window.statusbar.showMessage("An operation failed; monitoring paused. See the diagnostic log.")

    locals_for_errors = {}
    sys.excepthook = report_exception
    app = QApplication(sys.argv)
    app.setApplicationName("Project Monitor")
    app.setOrganizationName("project-monitor")

    config = ConfigManager(CONFIG_PATH)
    db = Database(DB_PATH)

    window = MainWindow(db, config)
    shutdown = ShutdownController(window)
    locals_for_errors["window"] = window
    window.show()

    try:
        result = app.exec()
    finally:
        shutdown.restore()
    sys.exit(result)


if __name__ == "__main__":
    main()
