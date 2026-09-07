"""Route process shutdown through Qt so background checks can clean up."""
import signal
from PyQt6.QtCore import QObject, QTimer


class ShutdownController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending = False
        self.previous = {}
        for number in (signal.SIGTERM, signal.SIGINT):
            self.previous[number] = signal.signal(number, self.request)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def request(self, *_):
        # Signal handlers never enter Qt or interrupt an account switch.
        self.pending = True

    def check(self):
        if self.pending and not self.window._switch_in_progress:
            self.timer.stop()
            self.window.close()

    def restore(self):
        self.timer.stop()
        for number, handler in self.previous.items():
            signal.signal(number, handler)
