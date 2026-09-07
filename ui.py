import logging
import json
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QToolBar, QStatusBar,
    QMessageBox, QSystemTrayIcon, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QProgressBar, QFrame, QWidget, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem, QComboBox, QSplitter, QGraphicsDropShadowEffect, QSizePolicy, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer, QSize, QDateTime, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (
    QAction, QIcon, QPixmap, QColor, QFont, QPalette,
    QLinearGradient, QPainter, QBrush, QPen, QFontDatabase,
)

from app.db import Database
from app.csv_import import import_accounts_from_csv, preview_csv
from app.codex import get_status
from app.monitor import ExhaustionMonitor, StatusWorker, AccountSwitchWorker
from app.usage import UsageWorker, usage_view
from config import ConfigManager


DATA_DIR = Path.home() / ".local" / "share" / "project-monitor"
DB_PATH = DATA_DIR / "data" / "monitor.db"
CONFIG_PATH = DATA_DIR / "config.json"

from app.theme import C, T, theme_style, desktop_theme
from app.usage_charts import UsageChartsDelegate


STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {T['bg']};
    color: {T['text']};
}}
QWidget {{
    color: {T['text']};
    font-size: 13px;
}}
QToolBar {{
    background-color: {T['bg_light']};
    border-bottom: 1px solid {T['border']};
    padding: 6px 8px;
    spacing: 6px;
}}
QToolBar::separator {{
    background: {T['border']};
    width: 1px;
    margin: 4px 6px;
}}
QToolBar QToolButton, QToolBar QPushButton {{
    background-color: {T['surface']};
    color: {T['text']};
    border: 1px solid {T['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 20px;
}}
QToolBar QToolButton:hover, QToolBar QPushButton:hover {{
    background-color: {T['surfaceHover']};
    border-color: {T['accent']};
}}
QToolBar QToolButton:pressed, QToolBar QPushButton:pressed {{
    background-color: {T['accent']};
    color: {T['onAccent']};
}}
QToolBar QToolButton:disabled {{
    background-color: {T['bg_card']};
    color: {T['textMuted']};
    border-color: {T['bg_card']};
}}
QTableWidget {{
    background-color: {T['bg_card']};
    border: 1px solid {T['border']};
    border-radius: 8px;
    gridline-color: {T['border']};
    selection-background-color: {T['surfaceHover']};
    selection-color: {T['text']};
    font-size: 13px;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {T['border']};
}}
QTableWidget::item:selected {{
    background-color: {T['surfaceHover']};
}}
QHeaderView::section {{
    background-color: {T['surface']};
    color: {T['textDim']};
    border: none;
    border-bottom: 1px solid {T['border']};
    padding: 10px 12px;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QHeaderView::section:horizontal:hover {{
    background-color: {T['surfaceHover']};
    color: {T['text']};
}}
QScrollBar:vertical {{
    background: {T['bg_card']}; width: 10px; margin: 4px 1px;
}}
QScrollBar::handle:vertical {{
    background: {T['border']}; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {T['textDim']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QStatusBar {{
    background-color: {T['bg_light']};
    border-top: 1px solid {T['border']};
    color: {T['textDim']};
    font-size: 12px;
    padding: 2px 8px;
}}
QPushButton {{
    background-color: {T['surface']};
    color: {T['text']};
    border: 1px solid {T['border']};
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: 500;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {T['surfaceHover']};
    border-color: {T['accent']};
}}
QPushButton:pressed {{
    background-color: {T['accent']};
    color: {T['onAccent']};
}}
QLineEdit {{
    background-color: {T['surface']};
    color: {T['text']};
    border: 1px solid {T['border']};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {T['accent']};
    selection-color: {T['onAccent']};
}}
QLineEdit:focus {{
    border-color: {T['accent']};
}}
QLineEdit::placeholder {{
    color: {T['textMuted']};
}}
QLabel {{
    color: {T['text']};
}}
QProgressBar {{
    background-color: {T['surface']};
    border: none;
    border-radius: 4px;
    max-height: 8px;
    min-height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{
    border-radius: 4px;
}}
QMenu {{
    background-color: {T['bg_light']};
    border: 1px solid {T['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {T['surfaceHover']};
    color: {T['accent']};
}}
QMessageBox {{
    background-color: {T['bg']};
}}
QMessageBox QLabel {{
    color: {T['text']};
}}
QMessageBox QPushButton {{
    min-width: 80px;
}}
"""


# ── Helpers ────────────────────────────────────────────────────

def mask_token(token):
    """A fixed-width identifier; token length never determines table width."""
    return "…" + token[-4:] if len(token) > 4 else "••••"


def format_timestamp(ts_str):
    if not ts_str:
        return "Never"
    try:
        dt = QDateTime.fromString(ts_str, Qt.DateFormat.ISODate)
        if not dt.isValid():
            return "Unknown"
        return dt.toLocalTime().toString("MMM d, h:mm AP")
    except Exception:
        return "Unknown"


def format_cooldown_remaining(cooldown_until_str, now_dt):
    if not cooldown_until_str:
        return None, 0
    try:
        cd_dt = QDateTime.fromString(cooldown_until_str, Qt.DateFormat.ISODate)
        if not cd_dt.isValid():
            return None, 0
        secs = int(now_dt.secsTo(cd_dt))
        if secs <= 0:
            return None, 0
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}", secs
    except Exception:
        return None, 0


def account_status_text(acc, now):
    """Return (status, is_cooldown, is_active) for an account."""
    if acc["is_active"]:
        return "Current", False, True
    if not acc["in_rotation"]:
        return "Paused", False, False
    usage = usage_view(acc, now.toSecsSinceEpoch())
    return usage['state'], usage['blocked'], False


# ── Custom delegates ──────────────────────────────────────────

class CenteredItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignmentFlag.AlignCenter


class StatusBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        fg, bg = {
            "Current": (C['greenBright'], C['greenDim']),
            "Available": (C['accent'], C['accentDim']),
            "Ready": (C['green'], C['greenDim']),
            "Nearly used up": (C['orange'], C['orangeDim']),
            "Limit reached": (C['red'], C['redDim']),
            "Cooling down": (C['orange'], C['orangeDim']),
            "Paused": (C['textDim'], C['surface']),
        }.get(text, (C['textDim'], C['surface']))
        rect = option.rect.adjusted(10, 20, -10, -20)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QColor(fg))
        font = painter.font()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class SwitchButtonDelegate(QStyledItemDelegate):
    """Renders 'Switch' or 'Cooldown' button per row state."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        btn_rect = rect.adjusted(8, 4, -8, -4)

        # Determine state from data stored in column 5
        model = index.model()
        row = index.row()
        is_cooldown = model.data(model.index(row, 6), Qt.ItemDataRole.UserRole)
        is_active = model.data(model.index(row, 7), Qt.ItemDataRole.UserRole)

        hovered = option.state & QStyle.StateFlag.State_MouseOver

        if is_active:
            bg = QColor(C['greenDim'])
            fg = QColor(C['green'])
            text = "Active"
        elif is_cooldown:
            bg = QColor(C['surface'])
            fg = QColor(C['textMuted'])
            text = "Cooldown"
        elif hovered:
            bg = QColor(C['accent'])
            fg = QColor(C['onAccent'])
            text = "Switch"
        else:
            bg = QColor(C['surface'])
            fg = QColor(C['text'])
            text = "Switch"

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(C['border']), 1))
        painter.drawRoundedRect(btn_rect, 6, 6)

        painter.setPen(QPen(fg))
        font = painter.font()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == event.Type.MouseButtonRelease:
            row = index.row()
            is_cooldown = model.data(model.index(row, 6), Qt.ItemDataRole.UserRole)
            is_active = model.data(model.index(row, 7), Qt.ItemDataRole.UserRole)
            if not is_cooldown and not is_active:
                self.callback(row)
            return True
        return False


# ── Main Window ────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config
        self._selected_id = None
        self._switch_in_progress = False
        self._closing = False
        self.theme = desktop_theme()
        self._usage_worker = None
        self.setWindowTitle("Project Monitor")
        self.setMinimumSize(860, 520)
        self.resize(1120, 740)

        theme_style(self, STYLESHEET)

        self._setup_toolbar()
        self._setup_table()
        self._setup_statusbar()
        self._setup_tray()
        self._setup_timer()
        self._setup_monitor()

        self.refresh_table()
        self.theme.changed.connect(self._refresh_theme)
        self.setWindowIcon(self._make_icon())
        self.usage_timer = QTimer(self)
        self.usage_timer.setInterval(5 * 60 * 1000)
        self.usage_timer.timeout.connect(self.refresh_usage)
        # Start network workers only in the real desktop application.
        if self.tray_icon:
            self.usage_timer.start()
            QTimer.singleShot(500, self.refresh_usage)

    def _setup_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.toolbar)

        self.menu_button = QPushButton("Menu")
        self.account_menu = QMenu(self.menu_button)
        self.account_menu.addAction("Import CSV…", self.import_csv)
        self.account_menu.addAction("Add account…", self.add_account)
        self.account_menu.addSeparator()
        self.remove_action = self.account_menu.addAction("Remove selected account…", self.remove_account)
        self.remove_action.setEnabled(False)
        self.menu_button.setMenu(self.account_menu)
        self.toolbar.addWidget(self.menu_button)

        self.btn_next = QPushButton("  Rotate account  ")
        theme_style(self.btn_next, f"""
            QPushButton {{
                background-color: {T['green']};
                color: {T['onGreen']};
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {T['greenBright']};
            }}
            QPushButton:disabled {{
                background-color: {T['surface']};
                color: {T['textMuted']};
                border: 1px solid {T['border']};
            }}
        """)
        self.btn_next.clicked.connect(self.switch_to_next_available)

        self.btn_switch = QPushButton("  Switch to Selected  ")
        self.btn_switch.setEnabled(False)
        theme_style(self.btn_switch, f"""
            QPushButton {{
                background-color: {T['accent']};
                color: {T['onAccent']};
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {T['accentHover']};
            }}
            QPushButton:disabled {{
                background-color: {T['surface']};
                color: {T['textMuted']};
                border: 1px solid {T['border']};
            }}
        """)
        self.btn_switch.clicked.connect(self.switch_account)
        self.switch_action = self.toolbar.addWidget(self.btn_switch)
        self.switch_action.setVisible(False)

        self.session_toolbar = self.toolbar
        self.session_toolbar.addWidget(QLabel("  Mode:  "))
        self.rotation_mode = QComboBox()
        theme_style(self.rotation_mode, f"""
            QComboBox {{
                background: {T['surface']}; color: {T['text']};
                border: 1px solid {T['accent']}; border-radius: 6px;
                padding: 7px 12px; min-width: 280px;
            }}
            QComboBox QAbstractItemView {{
                background: {T['surface']}; color: {T['text']};
                selection-background-color: {T['accent']};
                selection-color: {T['onAccent']};
            }}
        """)
        self.rotation_mode.addItem("Manual — account only", "manual")
        self.rotation_mode.addItem("Semi-auto — switch + refresh", "semi_auto")
        self.rotation_mode.addItem("Full auto — detect + switch + refresh", "full_auto")
        saved_mode = self.config.get("rotation_mode", "manual")
        if saved_mode == "automatic":
            saved_mode = "full_auto"
        self.rotation_mode.setCurrentIndex(max(0, self.rotation_mode.findData(saved_mode)))
        self.rotation_mode.setToolTip(
            "Manual: switch accounts only.\n"
            "Semi-auto: click to switch and refresh only exhausted open chats.\n"
            "Full auto: detect exhaustion, switch accounts and refresh exhausted chats."
        )
        self.session_toolbar.addWidget(self.rotation_mode)
        self.session_toolbar.addWidget(self.btn_next)
        self.full_access = QCheckBox("Full Access")
        self.full_access.setChecked(self.config.get("resume_full_access", True))
        self.full_access.setToolTip("Resumed chats can run commands without sandboxing or approval prompts")
        self.full_access.toggled.connect(
            lambda checked: self.config.set("resume_full_access", checked)
        )
        self.session_toolbar.addWidget(self.full_access)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

    def _setup_table(self):
        self.table = QTableWidget()
        # Name, Usage, Status, Reset, Last used, hidden switch metadata.
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Account name", "Usage remaining", "Status", "Reset / cooldown", "Last used", "", "", ""]
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.moveSection(header.visualIndex(2), 1)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setColumnWidth(1, 168)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 204)
        self.table.setColumnWidth(4, 176)
        self.table.setColumnWidth(5, 90)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(72)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setColumnHidden(5, True)
        self.table.setColumnHidden(6, True)
        self.table.setColumnHidden(7, True)

        self.table.setItemDelegateForColumn(1, UsageChartsDelegate(self.table))
        self.table.setItemDelegateForColumn(2, StatusBadgeDelegate(self.table))
        self.table.setItemDelegateForColumn(3, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(4, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(
            5, SwitchButtonDelegate(self._on_switch_clicked, self.table)
        )

        self.table.currentCellChanged.connect(self._on_row_selected)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(18)
        summary = QHBoxLayout()
        summary.setSpacing(12)
        self.summary_values = {}
        self.summary_notes = {}
        for key, title, accent, stretch in (
            ("current", "CURRENT ACCOUNT", T['greenBright'], 2),
            ("ready", "READY TO USE", T['accent'], 1),
            ("cooldown", "NEXT RESET", T['orange'], 1),
        ):
            card = QFrame()
            card.setObjectName("summaryCard")
            theme_style(card, f"QFrame#summaryCard {{ background: {T['bg_card']}; border: 1px solid {T['border']}; border-radius: 10px; }}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(6)
            heading = QLabel(title)
            theme_style(heading, f"font-size: 11px; font-weight: 600; color: {T['textDim']};")
            value = QLabel("—")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            theme_style(value, f"font-size: 24px; font-weight: 700; color: {accent};")
            note = QLabel("")
            note.setWordWrap(True)
            theme_style(note, f"font-size: 12px; color: {T['textDim']};")
            for widget in (heading, value, note):
                card_layout.addWidget(widget)
            self.summary_values[key] = value
            self.summary_notes[key] = note
            summary.addWidget(card, stretch)
        layout.addLayout(summary)
        title_row = QHBoxLayout()
        title = QLabel("Accounts")
        theme_style(title, "font-size: 20px; font-weight: 700;")
        self.account_count = QLabel("")
        theme_style(self.account_count, f"color: {T['textDim']};")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.account_count)
        self.btn_usage = QPushButton("Refresh usage")
        self.btn_usage.setToolTip("Read OpenAI usage for all saved accounts without switching or restarting chats")
        self.btn_usage.clicked.connect(self.refresh_usage)
        title_row.addWidget(self.btn_usage)
        layout.addLayout(title_row)
        layout.addWidget(self.table, 1)
        self.setCentralWidget(content)

    def refresh_usage(self):
        if self._closing or self._switch_in_progress:
            return
        if self._usage_worker is not None:
            return
        accounts = self.db.get_all_accounts()
        if not accounts:
            return
        self.btn_usage.setEnabled(False)
        self._usage_worker = UsageWorker(accounts, self)
        self._usage_worker.account_ready.connect(self._usage_received)
        self._usage_worker.progress.connect(self._usage_progress)
        self._usage_worker.finished.connect(self._usage_finished)
        self._usage_worker.start()

    def _usage_progress(self, current, total):
        if not self._closing:
            self.btn_usage.setText(f"Checking {current}/{total}…")

    def _usage_received(self, account_id, token, data, error, checked):
        if self._closing:
            return
        account = self.db.get_account(account_id)
        if account is None or account['token'] != token:
            return
        fields = dict(usage_error=error, usage_attempted_at=checked)
        if data is not None:
            fields.update(usage_json=json.dumps(data), usage_checked_at=checked)
        self.db.update_account(account_id, **fields)
        self._safe_tick()

    def _usage_finished(self):
        if not self._closing:
            self.btn_usage.setText("Refresh usage")
            self.btn_usage.setEnabled(True)
        if self._usage_worker is not None:
            self._usage_worker.deleteLater()
        self._usage_worker = None

    def _render_usage(self, row, account, now):
        usage = usage_view(account, now.toSecsSinceEpoch())
        windows = sorted(usage['windows'], key=lambda w: (w['limit'] != 'codex', w['minutes']))
        lines = []
        details = []
        for window in windows:
            minutes = window['minutes']
            label = f"{minutes / 1440:g}d" if minutes >= 1440 else f"{minutes / 60:g}h" if minutes >= 60 else f"{minutes:g}m"
            lines.append(f"{label}: {100 - window['used']:g}% left")
            stamp = QDateTime.fromSecsSinceEpoch(int(window['reset']), Qt.TimeSpec.UTC).toString(Qt.DateFormat.ISODate)
            details.append(f"{window['limit']} · {label} · resets {format_timestamp(stamp)}")
        text = ' · '.join(lines[:2]) if lines else 'Usage not reported' if usage['checked'] else 'Not checked'
        age = max(0, int(now.toSecsSinceEpoch() - usage['checked']))
        checked = f"Checked {age // 60}m ago" if age >= 60 else 'Checked just now'
        if usage['checked']:
            text += '\n' + checked
        if usage['error'] or usage['state'] in ('Stale', 'Check reset'):
            text = text.split('\n')[0] + '\n' + usage['state'] + ' · refresh needed'
        item = self.table.item(row, 1)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(row, 1, item)
        item.setText(text)
        color = 'orange' if usage['state'] == 'Nearly used up' else 'red' if usage['blocked'] else 'green' if usage['state'] == 'Ready' else 'textDim'
        item.setForeground(QColor(C[color]))
        if usage['reset_credits'] is not None:
            details.append(f"Available reset credits: {usage['reset_credits']}")
        if usage['checked']:
            details.append('Last checked: ' + format_timestamp(account['usage_checked_at']))
        if usage['error']:
            details.append(usage['error'])
        details.extend(usage['reasons'])
        item.setToolTip('\n'.join(details))
        charts = []
        for minutes, label, title in ((300, '5H', 'Five-hour usage'), (10080, '7D', 'Weekly usage')):
            window = next((w for w in windows if w['minutes'] == minutes), None)
            tooltip = [title]
            if window:
                tooltip.append(f"{100 - window['used']:g}% left · {window['used']:g}% used")
                reset = QDateTime.fromSecsSinceEpoch(int(window['reset']), Qt.TimeSpec.UTC).toString(Qt.DateFormat.ISODate)
                tooltip.append('Resets: ' + format_timestamp(reset))
            else:
                tooltip.append('OpenAI has not reported this usage window')
            if usage['checked']:
                tooltip.append(checked)
                tooltip.append('Last checked: ' + format_timestamp(account['usage_checked_at']))
            else:
                tooltip.append('Not checked yet')
            if usage['error']:
                tooltip.append(usage['error'])
            if usage['state'] in ('Stale', 'Check reset', 'Check failed'):
                tooltip.append(usage['state'] + ' — refresh needed')
            tooltip.extend(usage['reasons'])
            if usage['reset_credits'] is not None:
                tooltip.append(f"Available reset credits: {usage['reset_credits']}")
            fresh = bool(window and usage['checked'] and
                         now.toSecsSinceEpoch() - usage['checked'] <= 600 and
                         usage['state'] != 'Cooling down' and not usage['error'] and
                         window['reset'] > now.toSecsSinceEpoch())
            charts.append(dict(label=label, remaining=100 - window['used'] if window else None,
                               fresh=fresh, tooltip='\n'.join(tooltip)))
        item.setData(Qt.ItemDataRole.UserRole, charts)
        reset_item = self.table.item(row, 3)
        if not reset_item:
            reset_item = QTableWidgetItem()
            self.table.setItem(row, 3, reset_item)
        if usage['reset']:
            seconds = max(0, int(usage['reset'] - now.toSecsSinceEpoch()))
            stamp = QDateTime.fromSecsSinceEpoch(int(usage['reset']), Qt.TimeSpec.UTC).toString(Qt.DateFormat.ISODate)
            source = 'Local cooldown' if usage['state'] == 'Cooling down' else 'OpenAI reset'
            reset_item.setText(f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}\n{format_timestamp(stamp)}")
            reset_item.setToolTip(source + '\n' + '\n'.join(details))
        else:
            reset_item.setText('Reset not reported' if usage['checked'] else 'Not checked')
            reset_item.setToolTip('\n'.join(details))
        reset_item.setForeground(QColor(C['orange'] if usage['blocked'] else C['textDim']))
        return usage

    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")

    def _make_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(C['accent'])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QPen(QColor(C['onAccent']), 4))
        font = QFont(QApplication.font())
        font.setPointSize(22)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PM")
        painter.end()
        return QIcon(pixmap)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon(self._make_icon(), self)
        self.tray_menu = QMenu()
        self.tray_menu.addAction("Show Window", self._show_from_tray)
        self.tray_menu.addSeparator()
        self._tray_monitor_action = self.tray_menu.addAction("Monitor: OFF")
        self._tray_monitor_action.triggered.connect(self._toggle_monitor)
        self.tray_menu.addSeparator()
        self._tray_status_action = self.tray_menu.addAction("Token: --")
        self._tray_status_action.setEnabled(False)
        self._tray_process_action = self.tray_menu.addAction("Processes: --")
        self._tray_process_action.setEnabled(False)
        self._tray_active_action = self.tray_menu.addAction("Active: --")
        self._tray_active_action.setEnabled(False)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Quit", self._quit_app)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _refresh_theme(self):
        if self._closing:
            return
        # Repaint in place; preserve selected account, scroll, workers and mode.
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            if not name:
                continue
            active = self.table.item(row, 7)
            active = bool(active and active.data(Qt.ItemDataRole.UserRole))
            blocked = self.table.item(row, 6)
            blocked = bool(blocked and blocked.data(Qt.ItemDataRole.UserRole))
            name.setForeground(QColor(C['greenBright'] if active else C['text']))
            font = name.font()
            font.setFamily(QApplication.font().family())
            name.setFont(font)
            last_used = self.table.item(row, 4)
            reset = self.table.item(row, 3)
            if last_used:
                last_used.setForeground(QColor(C['text']))
            if reset:
                reset.setForeground(QColor(C['orange'] if blocked else C['textDim']))
        self._highlight_active_row()
        self.table.viewport().update()
        icon = self._make_icon()
        self.setWindowIcon(icon)
        if self.tray_icon:
            self.tray_icon.setIcon(icon)

    def _setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._safe_tick)
        self.timer.start(1000)

    def _setup_monitor(self):
        self.monitor = ExhaustionMonitor(self.db, self.config)
        self.monitor.exhaustion_detected.connect(self._on_exhaustion_detected)
        self.monitor.status_update.connect(self._on_monitor_status)
        self._monitor_active = False
        self._cached_login = (False, "Checking status")
        self.status_worker = StatusWorker(self)
        self.status_worker.status_ready.connect(self._on_login_status)
        if self.tray_icon:
            self.status_worker.start()
        self.rotation_mode.currentIndexChanged.connect(self._rotation_mode_changed)
        self._rotation_mode_changed()

    def _rotation_mode_changed(self, *_):
        mode = self.rotation_mode.currentData()
        self.config.set("rotation_mode", mode)
        self._monitor_active = mode == "full_auto"
        self.full_access.setEnabled(mode != "manual")
        if self._monitor_active:
            self.monitor.start_monitoring()
        else:
            self.monitor.stop_monitoring()
            self.monitor.wait()
        if mode == "manual":
            self.btn_next.setText("  Rotate account  ")
            self.btn_next.setToolTip("Switch accounts only; open chats are not restarted")
            message = "Manual: rotate accounts only. Open chats stay as they are."
        elif mode == "semi_auto":
            self.btn_next.setText("  Rotate + refresh exhausted chats  ")
            self.btn_next.setToolTip("Click to switch account and refresh only open chats that ran out of tokens")
            message = "Semi-auto: click to switch accounts and refresh exhausted chats. Healthy chats stay as they are."
        else:
            self.btn_next.setText("  Rotate + refresh now  ")
            self.btn_next.setToolTip("Full auto is watching; click to switch now and refresh only exhausted chats")
            message = "Full auto: watching for exhaustion. Offline checks wait without changing accounts or chats."
        self.statusbar.showMessage(message)

    def _toggle_monitor(self):
        self.rotation_mode.setCurrentIndex(0 if self._monitor_active else 2)

    def _on_login_status(self, logged_in, message):
        if self._closing:
            return
        self._cached_login = (logged_in, message)
        self._update_tray_menu()

    def _on_exhaustion_detected(self, reason):
        # Ignore queued detections after disabling automatic mode or during a switch.
        if not self._monitor_active or self._switch_in_progress:
            return
        from app.codex import get_exhausted_codex_sessions
        if not get_exhausted_codex_sessions():
            return
        next_account = self.monitor.find_next_account()
        if not next_account:
            self.rotation_mode.setCurrentIndex(0)
            self.statusbar.showMessage("Full auto paused: no available accounts. Wait for a reset or add an account, then select Full auto again.")
            if self.tray_icon:
                self.tray_icon.showMessage("No accounts available", "Full auto paused until an account is available.")
            return
        self._confirm_and_switch(next_account, exhausted_only=True, automatic=True)

    def _confirm_and_switch(self, acc, mark_current_exhausted=True, resume_sessions=None,
                            exhausted_only=True, automatic=False):
        if self._switch_in_progress:
            return
        if resume_sessions is None:
            resume_sessions = self.rotation_mode.currentData() != "manual"
        self._switch_in_progress = True
        self._switch_was_automatic = automatic
        self.monitor._switching = True
        self.status_worker._pause = True
        self.statusbar.showMessage(f"Checking connection before switching to {acc['name']}...")
        self.btn_switch.setEnabled(False)
        self.btn_next.setEnabled(False)
        self.rotation_mode.setEnabled(False)
        self.toolbar.setEnabled(False)
        self.table.setEnabled(False)
        options = dict(mark_current_exhausted=mark_current_exhausted,
                       resume_sessions=resume_sessions, exhausted_only=exhausted_only,
                       full_access=self.full_access.isChecked())
        self._switch_worker = AccountSwitchWorker(self.db.db_path, self.config, acc, options, self)
        self._switch_worker.status_update.connect(self._on_monitor_status)
        self._switch_worker.finished.connect(self._finish_switch)
        self._switch_worker.start()

    def _finish_switch(self):
        success, name, restarted, restart_msg = self._switch_worker.result
        automatic = self._switch_was_automatic
        self._switch_in_progress = False
        self.monitor._switching = False
        self.status_worker._pause = False
        self.btn_next.setEnabled(True)
        self.rotation_mode.setEnabled(True)
        self.toolbar.setEnabled(True)
        self.table.setEnabled(True)
        self.refresh_table()
        if success:
            self.refresh_table()
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "Account Switched",
                    f"Now using: {name}\n{restart_msg}",
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
            self.statusbar.showMessage(f"Switched to {name}. {restart_msg.splitlines()[0]}")
            if any(word in restart_msg.lower() for word in ("could not", "untouched", "unavailable", "nothing was stopped")):
                if automatic:
                    self.rotation_mode.setCurrentIndex(0)
                QMessageBox.warning(self, "Account switched — check terminals", restart_msg)
        else:
            self.statusbar.showMessage(f"Switch failed: {name}")
            if automatic and name.startswith("Offline or Codex service unavailable"):
                self.monitor._notified_sessions.clear()
                return
            if automatic:
                self.rotation_mode.setCurrentIndex(0)
            QMessageBox.warning(self, "Switch Failed", f"Could not switch account:\n{name}")

        self.btn_next.setEnabled(True)

    def _on_monitor_status(self, msg):
        self.statusbar.showMessage(msg)

    def _show_monitor_popup(self, pos):
        from PyQt6.QtWidgets import QMenu
        from app.codex import get_codex_pids, get_status

        menu = QMenu(self)
        theme_style(menu, f"""
            QMenu {{
                background-color: {T['bg_light']};
                border: 1px solid {T['border']};
                border-radius: 8px;
                padding: 8px;
                min-width: 220px;
            }}
            QMenu::item {{
                padding: 8px 16px;
                border-radius: 4px;
                color: {T['text']};
            }}
            QMenu::item:selected {{
                background-color: {T['surfaceHover']};
                color: {T['accent']};
            }}
            QMenu::item:disabled {{
                color: {T['textDim']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {T['border']};
                margin: 4px 8px;
            }}
        """)

        state = "ON" if self._monitor_active else "OFF"
        header = menu.addAction(f"Monitor: {state}")
        header.setEnabled(False)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        menu.addSeparator()

        pids = self.status_worker.pids
        if pids:
            pid_action = menu.addAction(f"Codex processes: {len(pids)}")
            pid_action.setEnabled(False)
            for pid in pids:
                pid_item = menu.addAction(f"  PID {pid}")
                pid_item.setEnabled(False)
        else:
            no_proc = menu.addAction("No codex processes running")
            no_proc.setEnabled(False)

        menu.addSeparator()

        logged_in, info = self._cached_login
        if logged_in:
            status_text = "Token: Active"
        else:
            status_text = "Token: Status unavailable" if "unavailable" in info.lower() or "checking" in info.lower() else "Token: Not logged in"

        status_action = menu.addAction(status_text)
        status_action.setEnabled(False)

        menu.addSeparator()

        active = self.db.get_active_account()
        if active:
            active_action = menu.addAction(f"Active: {active['name']}")
            active_action.setEnabled(False)
        else:
            no_active = menu.addAction("No active account")
            no_active.setEnabled(False)

        menu.addSeparator()

        if self._monitor_active:
            stop_action = menu.addAction("Stop Monitor")
            stop_action.triggered.connect(self._toggle_monitor)
        else:
            start_action = menu.addAction("Start Monitor")
            start_action.triggered.connect(self._toggle_monitor)

        menu.exec(self.rotation_mode.mapToGlobal(self.rotation_mode.rect().bottomLeft()))

    def refresh_table(self):
        accounts = self.db.get_all_accounts()
        # Replaced cell widgets are deleted later by Qt. Hide them immediately
        # so old countdown labels cannot flash at the top-left during refresh.
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 3)
            if widget:
                widget.hide()
        self.table.setRowCount(len(accounts))

        now = QDateTime.currentDateTimeUtc()

        self._update_account_summary(accounts, now)

        for row, acc in enumerate(accounts):
            is_active = bool(acc["is_active"])
            cd_text, secs = format_cooldown_remaining(acc["cooldown_until"], now)
            is_cooldown = bool(cd_text and secs > 0)

            # ── Name column (with active row highlight) ──
            name_item = QTableWidgetItem(acc["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, acc["id"])
            font = name_item.font()
            font.setWeight(QFont.Weight.DemiBold)
            font.setPointSize(12)
            name_item.setFont(font)
            if is_active:
                name_item.setForeground(QColor(C['greenBright']))
            name_item.setToolTip(acc["name"] + "\nToken ID: " + mask_token(acc["token"]))
            self.table.setItem(row, 0, name_item)

            usage = self._render_usage(row, acc, now)
            is_cooldown = usage['blocked']
            status, _, _ = account_status_text(acc, now)
            status_item = QTableWidgetItem(status)
            self.table.setItem(row, 2, status_item)

            # ── Last used ──
            last_item = QTableWidgetItem(format_timestamp(acc["last_used_at"]))
            last_item.setForeground(QColor(C['text']))
            self.table.setItem(row, 4, last_item)

            # ── Hidden columns for button delegate state ──
            cd_flag = QTableWidgetItem()
            cd_flag.setData(Qt.ItemDataRole.UserRole, is_cooldown)
            self.table.setItem(row, 6, cd_flag)

            active_flag = QTableWidgetItem()
            active_flag.setData(Qt.ItemDataRole.UserRole, is_active)
            self.table.setItem(row, 7, active_flag)

            # Store ID for switch button column
            id_item = QTableWidgetItem(str(acc["id"]))
            id_item.setData(Qt.ItemDataRole.UserRole, acc["id"])
            self.table.setItem(row, 5, id_item)

        # Highlight active row
        self._highlight_active_row()
        self.statusbar.showMessage(f"{len(accounts)} accounts loaded")

    def _update_account_summary(self, accounts, now):
        active = next((acc for acc in accounts if acc["is_active"]), None)
        ready = 0
        nearly = 0
        unchecked = 0
        cooling = []
        for acc in accounts:
            if acc["is_active"] or not acc["in_rotation"]:
                continue
            usage = usage_view(acc, now.toSecsSinceEpoch())
            if usage['state'] == 'Ready':
                ready += 1
            elif usage['state'] == 'Nearly used up':
                nearly += 1
            elif not usage['blocked']:
                unchecked += 1
            if usage['blocked'] and usage['reset']:
                reset = QDateTime.fromSecsSinceEpoch(int(usage['reset']), Qt.TimeSpec.UTC).toString(Qt.DateFormat.ISODate)
                remaining, secs = format_cooldown_remaining(reset, now)
                if secs:
                    cooling.append((secs, remaining, reset))
        self.summary_values["current"].setText(active["name"] if active else "No account selected")
        current_usage = usage_view(active, now.toSecsSinceEpoch()) if active else None
        self.summary_notes["current"].setText(current_usage['state'] if active else "Choose an account below")
        self.summary_values["ready"].setText(str(ready))
        self.summary_notes["ready"].setText(f"{nearly} nearly used up · {unchecked} need checking")
        if cooling:
            _, remaining, reset = min(cooling)
            self.summary_values["cooldown"].setText(remaining)
            self.summary_notes["cooldown"].setText(f"{format_timestamp(reset)} · {len(cooling)} cooling down")
        else:
            self.summary_values["cooldown"].setText("No reset pending")
            self.summary_notes["cooldown"].setText("Credit limits may have no reset time")
        self.account_count.setText(f"{len(accounts)} accounts · {ready} ready · {nearly} nearly used up")

    def _highlight_active_row(self):
        """Apply green left-border highlight to the active account row."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            is_active = self.table.item(row, 7)
            if is_active and is_active.data(Qt.ItemDataRole.UserRole):
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(QColor(C['activeRow']))
            else:
                for col in range(self.table.columnCount()):
                    cell = self.table.item(row, col)
                    if cell:
                        cell.setBackground(QColor(Qt.GlobalColor.transparent))

    def _safe_tick(self):
        if self._closing:
            return
        try:
            self._tick()
        except Exception:
            logging.getLogger(__name__).exception("Display refresh failed")
            self.timer.stop()
            self.monitor.stop_monitoring()
            self.statusbar.showMessage("Display refresh paused after an error; accounts and chats were left untouched")

    def _tick(self):
        now = QDateTime.currentDateTimeUtc()
        accounts = self.db.get_all_accounts()
        self._update_account_summary(accounts, now)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            acc_id = item.data(Qt.ItemDataRole.UserRole)
            acc = next((a for a in accounts if a["id"] == acc_id), None)
            if not acc:
                continue

            cd_text, secs = format_cooldown_remaining(acc["cooldown_until"], now)
            is_cooldown = bool(cd_text and secs > 0)
            is_active = bool(acc["is_active"])

            # Update status badge
            status, _, _ = account_status_text(acc, now)
            status_item = self.table.item(row, 2)
            if status_item:
                status_item.setData(Qt.ItemDataRole.DisplayRole, status)

            usage = self._render_usage(row, acc, now)
            is_cooldown = usage['blocked']

            # Update hidden flags for button delegate
            cd_flag = self.table.item(row, 6)
            if cd_flag:
                cd_flag.setData(Qt.ItemDataRole.UserRole, is_cooldown)
            active_flag = self.table.item(row, 7)
            if active_flag:
                active_flag.setData(Qt.ItemDataRole.UserRole, is_active)

            # Clear cooldown in DB when expired
            if not cd_text and acc["cooldown_until"]:
                self.db.update_account(acc_id, cooldown_until=None)
                if self.tray_icon and not is_active:
                    self.tray_icon.showMessage(
                        "Cooldown ended",
                        f"{acc['name']}: check usage to confirm availability",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )

        if not self._switch_in_progress:
            self._on_row_selected(self.table.currentRow(), 0, -1, -1)
        self._update_tray_menu()

    def _update_tray_menu(self):
        if not self.tray_icon:
            return
        from app.codex import get_codex_pids, get_status

        state = "ON" if self._monitor_active else "OFF"
        self._tray_monitor_action.setText(f"Mode: {self.rotation_mode.currentText().split(' —')[0]}")

        pids = self.status_worker.pids
        self._tray_process_action.setText(f"Processes: {len(pids)}")

        logged_in, info = self._cached_login
        self._tray_status_action.setText("Token: Active" if logged_in else "Token: Status unavailable")

        active = self.db.get_active_account()
        self._tray_active_action.setText(f"Active: {active['name']}" if active else "Active: None")

    def _on_row_selected(self, row, col, prev_row, prev_col):
        selected = row >= 0 and self.table.item(row, 0) is not None
        self.switch_action.setVisible(selected)
        self.remove_action.setEnabled(selected)
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                self._selected_id = item.data(Qt.ItemDataRole.UserRole)
                # Check if cooldown
                cd_flag = self.table.item(row, 6)
                active_flag = self.table.item(row, 7)
                is_cd = cd_flag and cd_flag.data(Qt.ItemDataRole.UserRole)
                is_act = active_flag and active_flag.data(Qt.ItemDataRole.UserRole)
                self.btn_switch.setEnabled(not is_cd and not is_act)
        else:
            self.btn_switch.setEnabled(False)

    def _on_switch_clicked(self, row):
        try:
            id_item = self.table.item(row, 0)
            if id_item:
                acc_id = id_item.data(Qt.ItemDataRole.UserRole)
                if acc_id:
                    self.select_account(acc_id)
        except Exception as e:
            self.statusbar.showMessage(f"Error: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def switch_to_next_available(self):
        """Mark the current account exhausted and switch to the next available."""
        try:
            next_account = self.db.get_next_available()
            if next_account:
                self._confirm_and_switch(next_account, exhausted_only=True)
                return

            QMessageBox.information(
                self,
                "No Accounts Available",
                "All accounts are either on cooldown, paused, or already active.\n\n"
                "Wait for a cooldown to expire or add/import more accounts.",
            )
        except Exception as e:
            self.statusbar.showMessage(f"Error: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def import_csv(self):
        dialog = CSVImportDialog(self.config.csv_path, self)
        if dialog.exec():
            path = dialog.get_path()
            if path:
                try:
                    count = import_accounts_from_csv(path, self.db)
                    self.config.set("csv_path", path)
                    self.refresh_table()
                    QMessageBox.information(
                        self, "Import Complete", f"Imported {count} accounts."
                    )
                except Exception as e:
                    QMessageBox.critical(self, "Import Error", str(e))

    def add_account(self):
        dialog = AddAccountDialog(self)
        if dialog.exec():
            name, token = dialog.get_values()
            if name and token:
                self.db.add_account(name, token)
                self.refresh_table()

    def remove_account(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Select an account to remove.")
            return
        item = self.table.item(row, 0)
        acc_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Remove account '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.remove_account(acc_id)
            self.refresh_table()

    def select_account(self, acc_id, mark_current_exhausted=False):
        if self._switch_in_progress:
            return
        acc = self.db.get_account(acc_id)
        if not acc:
            return

        # Check cooldown
        now = QDateTime.currentDateTimeUtc()
        usage = usage_view(acc, now.toSecsSinceEpoch())
        if usage['blocked']:
            QMessageBox.information(
                self,
                "Account unavailable",
                f"'{acc['name']}': {usage['state']}.\n\nRefresh usage to check its current limits.",
            )
            return

        if acc["is_active"]:
            QMessageBox.information(
                self,
                "Already Active",
                f"'{acc['name']}' is already the active account.",
            )
            return

        active = self.db.get_active_account()
        exhaustion_note = ""
        if mark_current_exhausted and active:
            exhaustion_note = (
                f"\n\nThis marks <b>{active['name']}</b> as used up and unavailable "
                f"until its quota resets."
            )

        mode = self.rotation_mode.currentData()
        resume_note = "\n\nOpen chats will stay as they are."
        if mode != "manual":
            resume_note = "\n\nOnly exhausted open chats will refresh in their original terminals. Healthy chats stay as they are."
            if self.full_access.isChecked():
                resume_note += " Full Access will be enabled."

        reply = QMessageBox.question(
            self,
            "Switch Account",
            f"Switch to <b>{acc['name']}</b>?\n\n"
            f"This will sign in with this account's token."
            f"{exhaustion_note}{resume_note}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._confirm_and_switch(
            acc, mark_current_exhausted=mark_current_exhausted,
            exhausted_only=True,
        )

    def switch_account(self):
        try:
            if self._selected_id:
                self.select_account(self._selected_id)
        except Exception as e:
            self.statusbar.showMessage(f"Error: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit_app(self):
        self.close()

    def closeEvent(self, event):
        if self._switch_in_progress:
            self.statusbar.showMessage("Finishing the current switch before closing")
            event.ignore()
            return
        self._closing = True
        self.timer.stop()
        self.usage_timer.stop()
        if self._usage_worker is not None:
            self._usage_worker.stop()
            self._usage_worker.wait()
        self.monitor.stop_monitoring()
        self.status_worker.stop()
        self.monitor.wait()
        self.status_worker.wait()
        self.db.close()
        event.accept()


# ── Add Account Dialog ─────────────────────────────────────────

class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Account")
        self.setMinimumWidth(400)
        theme_style(self, STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Add New Account")
        theme_style(title, f"font-size: 18px; font-weight: 700; color: {T['accent']};")
        layout.addWidget(title)

        name_lbl = QLabel("Name")
        theme_style(name_lbl, f"color: {T['textDim']}; font-size: 12px; font-weight: 600;")
        layout.addWidget(name_lbl)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Catherine Zafra")
        self.name_input.setMinimumHeight(38)
        layout.addWidget(self.name_input)

        token_lbl = QLabel("Access Token")
        theme_style(token_lbl, f"color: {T['textDim']}; font-size: 12px; font-weight: 600;")
        layout.addWidget(token_lbl)
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("at-xxxx...")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setMinimumHeight(38)
        layout.addWidget(self.token_input)

        layout.addSpacing(8)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        add_btn = QPushButton("Add Account")
        add_btn.setMinimumWidth(120)
        theme_style(add_btn, f"""
            QPushButton {{
                background-color: {T['accent']};
                color: {T['onAccent']};
                border: none;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {T['accentHover']};
            }}
        """)
        add_btn.clicked.connect(self._on_add)
        buttons.addWidget(add_btn)
        layout.addLayout(buttons)

        self.name_input.setFocus()

    def _on_add(self):
        if not self.name_input.text().strip():
            theme_style(self.name_input, f"border-color: {T['red']};")
            return
        if not self.token_input.text().strip():
            theme_style(self.token_input, f"border-color: {T['red']};")
            return
        self.accept()

    def get_values(self):
        return self.name_input.text().strip(), self.token_input.text().strip()


# ── CSV Import Dialog ──────────────────────────────────────────

class CSVImportDialog(QDialog):
    def __init__(self, current_csv_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Accounts from CSV")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        theme_style(self, STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Import from CSV")
        theme_style(title, f"font-size: 18px; font-weight: 700; color: {T['accent']};")
        layout.addWidget(title)

        hint = QLabel("CSV must have a 'Name' and 'Token' column.")
        theme_style(hint, f"color: {T['textDim']}; font-size: 12px;")
        layout.addWidget(hint)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.path_input = QLineEdit(current_csv_path)
        self.path_input.setPlaceholderText("Path to CSV file...")
        self.path_input.setMinimumHeight(36)
        file_row.addWidget(self.path_input)
        browse_btn = QPushButton("Browse")
        browse_btn.setMinimumWidth(90)
        browse_btn.setMinimumHeight(36)
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        preview_lbl = QLabel("Preview")
        theme_style(preview_lbl, f"color: {T['textDim']}; font-size: 12px; font-weight: 600; margin-top: 8px;")
        layout.addWidget(preview_lbl)

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setShowGrid(False)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.preview_table)

        self.status_label = QLabel("")
        theme_style(self.status_label, f"color: {T['textDim']}; font-size: 12px;")
        layout.addWidget(self.status_label)

        layout.addSpacing(4)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        import_btn = QPushButton("Import")
        import_btn.setMinimumWidth(120)
        theme_style(import_btn, f"""
            QPushButton {{
                background-color: {T['accent']};
                color: {T['onAccent']};
                border: none;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {T['accentHover']};
            }}
        """)
        import_btn.clicked.connect(self._on_import)
        buttons.addWidget(import_btn)
        layout.addLayout(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self.path_input.setText(path)
            self._load_preview(path)

    def _load_preview(self, path):
        try:
            headers, rows = preview_csv(path)
            self.preview_table.setColumnCount(len(headers))
            self.preview_table.setHorizontalHeaderLabels(headers)
            self.preview_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, h in enumerate(headers):
                    val = row.get(h, "")
                    if h.lower() == "token":
                        val = mask_token(val) if val else ""
                    self.preview_table.setItem(i, j, QTableWidgetItem(val))
            self.status_label.setText(f"Found {len(rows)} account(s)")
            theme_style(self.status_label, f"color: {T['green']}; font-size: 12px; font-weight: 600;")
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            theme_style(self.status_label, f"color: {T['red']}; font-size: 12px;")
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)

    def _on_import(self):
        path = self.path_input.text().strip()
        if not path:
            QMessageBox.warning(self, "No File", "Please select a CSV file.")
            return
        self.accept()

    def get_path(self):
        return self.path_input.text().strip()
