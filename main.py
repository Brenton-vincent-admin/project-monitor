import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from app.db import Database
from config import ConfigManager
from ui import MainWindow, DB_PATH, CONFIG_PATH


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Project Monitor")
    app.setOrganizationName("project-monitor")
    app.setStyle("Fusion")

    config = ConfigManager(CONFIG_PATH)
    db = Database(DB_PATH)

    window = MainWindow(db, config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
