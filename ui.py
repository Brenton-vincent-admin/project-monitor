import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QToolBar, QStatusBar,
    QMessageBox, QSystemTrayIcon, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QProgressBar, QFrame, QWidget, QStyledItemDelegate,
    QStyle, QComboBox, QSplitter, QGraphicsDropShadowEffect, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QSize, QDateTime, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (
    QAction, QIcon, QPixmap, QColor, QFont, QPalette,
    QLinearGradient, QPainter, QBrush, QPen, QFontDatabase,
)

from app.db import Database
from app.csv_import import import_accounts_from_csv, preview_csv
from app.codex import login_with_token, logout, get_status
from config import ConfigManager


DATA_DIR = Path.home() / ".local" / "share" / "project-monitor"
DB_PATH = DATA_DIR / "data" / "monitor.db"
CONFIG_PATH = DATA_DIR / "config.json"

# ── Color palette ──────────────────────────────────────────────
C = {
    "bg":           "#1a1b26",
    "bg_light":     "#24283b",
    "bg_card":      "#1f2335",
    "surface":      "#292e42",
    "surfaceHover": "#3b4261",
    "border":       "#3b4261",
    "text":         "#c0caf5",
    "textDim":      "#565f89",
    "textMuted":    "#414868",
    "accent":       "#7aa2f7",
    "accentHover":  "#89b4fa",
    "green":        "#9ece6a",
    "greenBright":  "#73daca",
    "greenDim":     "#3d5c1e",
    "orange":       "#e0af68",
    "orangeDim":    "#5c4a1e",
    "red":          "#f7768e",
    "redDim":       "#5c1e2a",
    "purple":       "#bb9af7",
    "cyan":         "#7dcfff",
    "pink":         "#ff7eb6",
    "activeRow":    "#1a3a2a",
    "activeBorder": "#9ece6a",
}

STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {C['bg']};
    color: {C['text']};
}}
QWidget {{
    color: {C['text']};
    font-family: "Inter", "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QToolBar {{
    background-color: {C['bg_light']};
    border-bottom: 1px solid {C['border']};
    padding: 6px 8px;
    spacing: 6px;
}}
QToolBar::separator {{
    background: {C['border']};
    width: 1px;
    margin: 4px 6px;
}}
QToolBar QToolButton, QToolBar QPushButton {{
    background-color: {C['surface']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 20px;
}}
QToolBar QToolButton:hover, QToolBar QPushButton:hover {{
    background-color: {C['surfaceHover']};
    border-color: {C['accent']};
}}
QToolBar QToolButton:pressed, QToolBar QPushButton:pressed {{
    background-color: {C['accent']};
    color: {C['bg']};
}}
QToolBar QToolButton:disabled {{
    background-color: {C['bg_card']};
    color: {C['textMuted']};
    border-color: {C['bg_card']};
}}
QTableWidget {{
    background-color: {C['bg_card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    gridline-color: {C['border']};
    selection-background-color: {C['surfaceHover']};
    selection-color: {C['text']};
    font-size: 13px;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {C['border']};
}}
QTableWidget::item:selected {{
    background-color: {C['surfaceHover']};
}}
QHeaderView::section {{
    background-color: {C['surface']};
    color: {C['textDim']};
    border: none;
    border-bottom: 2px solid {C['accent']};
    padding: 10px 12px;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QHeaderView::section:horizontal:hover {{
    background-color: {C['surfaceHover']};
    color: {C['text']};
}}
QStatusBar {{
    background-color: {C['bg_light']};
    border-top: 1px solid {C['border']};
    color: {C['textDim']};
    font-size: 12px;
    padding: 2px 8px;
}}
QPushButton {{
    background-color: {C['surface']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: 500;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {C['surfaceHover']};
    border-color: {C['accent']};
}}
QPushButton:pressed {{
    background-color: {C['accent']};
    color: {C['bg']};
}}
QLineEdit {{
    background-color: {C['surface']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {C['accent']};
    selection-color: {C['bg']};
}}
QLineEdit:focus {{
    border-color: {C['accent']};
}}
QLineEdit::placeholder {{
    color: {C['textMuted']};
}}
QLabel {{
    color: {C['text']};
}}
QProgressBar {{
    background-color: {C['surface']};
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
    background-color: {C['bg_light']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {C['surfaceHover']};
    color: {C['accent']};
}}
QMessageBox {{
    background-color: {C['bg']};
}}
QMessageBox QLabel {{
    color: {C['text']};
}}
QMessageBox QPushButton {{
    min-width: 80px;
}}
"""


# ── Helpers ────────────────────────────────────────────────────

def mask_token(token):
    if len(token) <= 12:
        return token[:4] + "*" * (len(token) - 8) + token[-4:]
    return token[:8] + "*" * (len(token) - 12) + token[-4:]


def format_timestamp(ts_str):
    if not ts_str:
        return "Never"
    try:
        dt = QDateTime.fromString(ts_str[:19], Qt.DateFormat.ISODate)
        if not dt.isValid():
            return "Unknown"
        return dt.toString("MMM d, h:mm AP")
    except Exception:
        return "Unknown"


def format_cooldown_remaining(cooldown_until_str, now_dt):
    if not cooldown_until_str:
        return None, 0
    try:
        cd_dt = QDateTime.fromString(cooldown_until_str[:19], Qt.DateFormat.ISODate)
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


def colored_badge(text, color, bg_dim):
    return (
        f'<span style="color:{color}; font-weight:600;">'
        f'<span style="background:{bg_dim}; padding:2px 8px; '
        f'border-radius:4px;">{text}</span></span>'
    )


def account_status_text(acc, now):
    """Return (badge_html, is_cooldown, is_active) for an account."""
    is_active = bool(acc["is_active"])
    in_rotation = bool(acc["in_rotation"])
    cd_text, _ = format_cooldown_remaining(acc["cooldown_until"], now)

    if is_active:
        return colored_badge("CURRENT", C['greenBright'], C['greenDim']), False, True
    if not in_rotation:
        return colored_badge("Paused", C['textMuted'], C['bg_light']), False, False
    if cd_text:
        return colored_badge("Cooldown", C['orange'], C['orangeDim']), True, False
    return colored_badge("Available", C['green'], C['greenDim']), False, False


# ── Custom delegates ──────────────────────────────────────────

class CenteredItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignmentFlag.AlignCenter


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
            fg = QColor(C['bg'])
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
        self.setWindowTitle("Project Monitor")
        self.setMinimumSize(860, 520)
        self.resize(960, 600)

        self.setStyleSheet(STYLESHEET)

        self._setup_toolbar()
        self._setup_table()
        self._setup_statusbar()
        self._setup_tray()
        self._setup_timer()

        self.refresh_table()

    def _setup_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.toolbar)

        self.toolbar.addAction("  Import CSV  ", self.import_csv)
        self.toolbar.addAction("  + Add Account  ", self.add_account)
        self.toolbar.addSeparator()

        self.btn_next = QPushButton("  Next Available  ")
        self.btn_next.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['green']};
                color: {C['bg']};
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {C['greenBright']};
            }}
            QPushButton:disabled {{
                background-color: {C['surface']};
                color: {C['textMuted']};
                border: 1px solid {C['border']};
            }}
        """)
        self.btn_next.clicked.connect(self.switch_to_next_available)
        self.toolbar.addWidget(self.btn_next)

        self.btn_switch = QPushButton("  Switch to Selected  ")
        self.btn_switch.setEnabled(False)
        self.btn_switch.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['accent']};
                color: {C['bg']};
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {C['accentHover']};
            }}
            QPushButton:disabled {{
                background-color: {C['surface']};
                color: {C['textMuted']};
                border: 1px solid {C['border']};
            }}
        """)
        self.btn_switch.clicked.connect(self.switch_account)
        self.toolbar.addWidget(self.btn_switch)

        self.toolbar.addSeparator()
        self.toolbar.addAction("  Remove  ", self.remove_account)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

        self.active_label = QLabel("")
        self.active_label.setStyleSheet(f"""
            color: {C['green']};
            font-size: 13px;
            font-weight: 700;
            padding: 4px 12px;
            background: {C['greenDim']};
            border-radius: 6px;
        """)
        self.toolbar.addWidget(self.active_label)

    def _setup_table(self):
        self.table = QTableWidget()
        # Columns: Name, Token, Status, Cooldown, Last Used, Switch(btn), [hidden: cooldown_flag, active_flag]
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Token", "Status", "Cooldown", "Last Used", "", "", ""]
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(5, 90)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setShowGrid(False)
        self.table.setColumnHidden(5, True)
        self.table.setColumnHidden(6, True)
        self.table.setColumnHidden(7, True)

        self.table.setItemDelegateForColumn(1, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(2, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(3, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(4, CenteredItemDelegate(self.table))
        self.table.setItemDelegateForColumn(
            5, SwitchButtonDelegate(self._on_switch_clicked, self.table)
        )

        self.table.currentCellChanged.connect(self._on_row_selected)
        self.setCentralWidget(self.table)

    def _setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(C['accent'])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QPen(QColor(C['bg']), 4))
        font = QFont("Inter", 22, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PM")
        painter.end()

        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), self)
        tray_menu = QMenu()
        tray_menu.addAction("Show Window", self._show_from_tray)
        tray_menu.addSeparator()
        tray_menu.addAction("Quit", self._quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def refresh_table(self):
        accounts = self.db.get_all_accounts()
        self.table.setRowCount(len(accounts))

        now = QDateTime.currentDateTimeUtc()

        # Update active account label in toolbar
        active = self.db.get_active_account()
        if active:
            self.active_label.setText(f"  Active: {active['name']}  ")
            self.active_label.show()
        else:
            self.active_label.setText("  No active account  ")
            self.active_label.setStyleSheet(f"""
                color: {C['textMuted']};
                font-size: 13px;
                font-weight: 700;
                padding: 4px 12px;
                background: {C['surface']};
                border-radius: 6px;
            """)
            self.active_label.show()

        for row, acc in enumerate(accounts):
            is_active = bool(acc["is_active"])
            cd_text, secs = format_cooldown_remaining(acc["cooldown_until"], now)
            is_cooldown = bool(cd_text and secs > 0)

            # ── Name column (with active row highlight) ──
            name_item = QTableWidgetItem(acc["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, acc["id"])
            font = name_item.font()
            font.setWeight(QFont.Weight.DemiBold)
            font.setPointSize(11)
            name_item.setFont(font)
            if is_active:
                name_item.setForeground(QColor(C['greenBright']))
            self.table.setItem(row, 0, name_item)

            # ── Token ──
            token_item = QTableWidgetItem(mask_token(acc["token"]))
            font = token_item.font()
            font.setFamily("monospace")
            font.setPointSize(10)
            token_item.setFont(font)
            token_item.setForeground(QColor(C['textDim']))
            self.table.setItem(row, 1, token_item)

            # ── Status badge ──
            badge_html, _, _ = account_status_text(acc, now)
            status_item = QTableWidgetItem()
            status_item.setData(Qt.ItemDataRole.DisplayRole, badge_html)
            self.table.setItem(row, 2, status_item)

            # ── Cooldown progress bar ──
            if is_cooldown:
                cd_widget = QWidget()
                cd_layout = QVBoxLayout(cd_widget)
                cd_layout.setContentsMargins(8, 4, 8, 4)
                cd_layout.setSpacing(3)

                cd_label = QLabel(cd_text)
                cd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cd_label.setFont(QFont("monospace", 10))
                cd_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {C['orange']}; background: transparent; border: none;")

                bar = QProgressBar()
                total = self.config.cooldown_seconds
                pct = max(0, min(100, int((1 - secs / total) * 100)))
                bar.setValue(pct)
                bar.setFormat("")
                bar.setTextVisible(False)
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        background-color: {C['surface']};
                        border: none;
                        border-radius: 3px;
                        max-height: 6px;
                        min-height: 6px;
                    }}
                    QProgressBar::chunk {{
                        background-color: {C['orange']};
                        border-radius: 3px;
                    }}
                """)

                cd_layout.addWidget(cd_label)
                cd_layout.addWidget(bar)
                self.table.setCellWidget(row, 3, cd_widget)
            else:
                cd_widget = QWidget()
                cd_layout = QVBoxLayout(cd_widget)
                cd_layout.setContentsMargins(8, 4, 8, 4)
                cd_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ready_label = QLabel("Ready")
                ready_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_active:
                    ready_label.setText("In Use")
                    ready_label.setStyleSheet(f"color: {C['greenBright']}; font-weight: 600; font-size: 12px; background: transparent; border: none;")
                else:
                    ready_label.setStyleSheet(f"color: {C['green']}; font-weight: 600; font-size: 12px; background: transparent; border: none;")
                cd_layout.addWidget(ready_label)
                self.table.setCellWidget(row, 3, cd_widget)

            # ── Last used ──
            last_item = QTableWidgetItem(format_timestamp(acc["last_used_at"]))
            last_item.setForeground(QColor(C['textDim']))
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

    def _tick(self):
        now = QDateTime.currentDateTimeUtc()
        accounts = self.db.get_all_accounts()
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
            badge_html, _, _ = account_status_text(acc, now)
            status_item = self.table.item(row, 2)
            if status_item:
                status_item.setData(Qt.ItemDataRole.DisplayRole, badge_html)

            # Update cooldown widget
            cd_widget = self.table.cellWidget(row, 3)
            if cd_widget:
                labels = cd_widget.findChildren(QLabel)
                bars = cd_widget.findChildren(QProgressBar)

                if is_cooldown and labels and bars:
                    labels[0].setText(cd_text)
                    labels[0].setStyleSheet(f"font-size: 12px; font-weight: 600; color: {C['orange']}; background: transparent; border: none;")
                    bars[0].show()
                    total = self.config.cooldown_seconds
                    pct = max(0, min(100, int((1 - secs / total) * 100)))
                    bars[0].setValue(pct)
                elif not is_cooldown and labels:
                    if is_active:
                        labels[0].setText("In Use")
                        labels[0].setStyleSheet(f"color: {C['greenBright']}; font-weight: 600; font-size: 12px; background: transparent; border: none;")
                    else:
                        labels[0].setText("Ready")
                        labels[0].setStyleSheet(f"color: {C['green']}; font-weight: 600; font-size: 12px; background: transparent; border: none;")
                    for b in bars:
                        b.hide()

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
                        "Account Ready",
                        f"{acc['name']} is available again",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )

    def _on_row_selected(self, row, col, prev_row, prev_col):
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
        """Switch to the next available account, skipping cooldown ones."""
        try:
            now = QDateTime.currentDateTimeUtc()
            accounts = self.db.get_all_accounts()

            # Find next available: in_rotation, not active, not on cooldown
            for acc in accounts:
                if not acc["in_rotation"] or acc["is_active"]:
                    continue
                cd_text, secs = format_cooldown_remaining(acc["cooldown_until"], now)
                if cd_text and secs > 0:
                    continue  # Skip cooldown accounts
                # Found one
                self.select_account(acc["id"])
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

    def select_account(self, acc_id):
        acc = self.db.get_account(acc_id)
        if not acc:
            return

        # Check cooldown
        now = QDateTime.currentDateTimeUtc()
        cd_text, secs = format_cooldown_remaining(acc["cooldown_until"], now)
        if cd_text and secs > 0:
            QMessageBox.information(
                self,
                "Account on Cooldown",
                f"'{acc['name']}' is on cooldown.\n\nAvailable in: {cd_text}",
            )
            return

        if acc["is_active"]:
            QMessageBox.information(
                self,
                "Already Active",
                f"'{acc['name']}' is already the active account.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Switch Account",
            f"Switch to <b>{acc['name']}</b>?\n\n"
            f"This will log out the current session and log in with this account's token.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.statusbar.showMessage(f"Switching to {acc['name']}...")
        self.btn_switch.setEnabled(False)
        self.btn_next.setEnabled(False)
        QApplication.processEvents()

        logout()
        success, msg = login_with_token(acc["token"])

        if success:
            now = QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate)
            cooldown_until_ts = QDateTime.currentDateTimeUtc().addSecs(
                self.config.cooldown_seconds
            ).toString(Qt.DateFormat.ISOFormat)
            self.db.set_active(acc_id)
            self.db.update_account(
                acc_id,
                cooldown_until=cooldown_until_ts,
                last_used_at=now,
            )
            self.statusbar.showMessage(f"Switched to {acc['name']}")
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "Account Switched",
                    f"Now using: {acc['name']}",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            self.refresh_table()
        else:
            self.statusbar.showMessage(f"Switch failed: {msg}")
            QMessageBox.warning(self, "Switch Failed", f"Could not switch account:\n{msg}")

        self.btn_next.setEnabled(True)

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
        self.db.close()
        QApplication.quit()

    def closeEvent(self, event):
        self.db.close()
        event.accept()


# ── Add Account Dialog ─────────────────────────────────────────

class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Account")
        self.setMinimumWidth(400)
        self.setStyleSheet(STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Add New Account")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C['accent']};")
        layout.addWidget(title)

        name_lbl = QLabel("Name")
        name_lbl.setStyleSheet(f"color: {C['textDim']}; font-size: 12px; font-weight: 600;")
        layout.addWidget(name_lbl)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Catherine Zafra")
        self.name_input.setMinimumHeight(38)
        layout.addWidget(self.name_input)

        token_lbl = QLabel("Access Token")
        token_lbl.setStyleSheet(f"color: {C['textDim']}; font-size: 12px; font-weight: 600;")
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
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['accent']};
                color: {C['bg']};
                border: none;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {C['accentHover']};
            }}
        """)
        add_btn.clicked.connect(self._on_add)
        buttons.addWidget(add_btn)
        layout.addLayout(buttons)

        self.name_input.setFocus()

    def _on_add(self):
        if not self.name_input.text().strip():
            self.name_input.setStyleSheet(f"border-color: {C['red']};")
            return
        if not self.token_input.text().strip():
            self.token_input.setStyleSheet(f"border-color: {C['red']};")
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
        self.setStyleSheet(STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Import from CSV")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C['accent']};")
        layout.addWidget(title)

        hint = QLabel("CSV must have a 'Name' and 'Token' column.")
        hint.setStyleSheet(f"color: {C['textDim']}; font-size: 12px;")
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
        preview_lbl.setStyleSheet(f"color: {C['textDim']}; font-size: 12px; font-weight: 600; margin-top: 8px;")
        layout.addWidget(preview_lbl)

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setShowGrid(False)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.preview_table)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {C['textDim']}; font-size: 12px;")
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
        import_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['accent']};
                color: {C['bg']};
                border: none;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {C['accentHover']};
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
            self.status_label.setStyleSheet(f"color: {C['green']}; font-size: 12px; font-weight: 600;")
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            self.status_label.setStyleSheet(f"color: {C['red']}; font-size: 12px;")
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
