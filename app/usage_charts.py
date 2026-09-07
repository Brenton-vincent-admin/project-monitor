"""Small vector usage charts painted inside existing table rows."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPen
from PyQt6.QtWidgets import QApplication, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QToolTip

from app.theme import C, mix


def usage_color(remaining):
    used = 1 - max(0, min(100, remaining)) / 100
    return QColor(mix(C['green'], C['orange'], used * 2) if used <= .5
                  else mix(C['orange'], C['red'], (used - .5) * 2))


class UsageChartsDelegate(QStyledItemDelegate):
    @staticmethod
    def chart_rects(rect):
        diameter = min(42, rect.height() - 16)
        center = rect.center()
        return [QRectF(center.x() + offset - diameter / 2,
                       center.y() - diameter / 2, diameter, diameter)
                for offset in (-34, 34)]

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ''
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        charts = index.data(Qt.ItemDataRole.UserRole) or []
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        for rect, chart in zip(self.chart_rects(option.rect), charts):
            remaining = chart['remaining']
            color = usage_color(remaining) if remaining is not None and chart['fresh'] else QColor(C['textDim'])
            painter.setPen(Qt.PenStyle.NoPen)
            empty = remaining == 0 and chart['fresh']
            painter.setBrush(QColor(C['redDim'] if empty else C['border']))
            painter.drawEllipse(rect)
            if remaining is not None:
                painter.setBrush(color)
                painter.drawPie(rect, 90 * 16, -round(remaining / 100 * 360 * 16))
            inner = rect.adjusted(5, 5, -5, -5)
            painter.setBrush(QColor(C['bg_card']))
            painter.drawEllipse(inner)
            if not chart['fresh']:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(C['textDim']), 1, Qt.PenStyle.DotLine))
                painter.drawEllipse(rect)
            painter.setPen(QColor(C['red'] if empty else C['text']))
            font = QFont(option.font)
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, chart['label'])
        painter.restore()

    def helpEvent(self, event, view, option, index):
        charts = index.data(Qt.ItemDataRole.UserRole) or []
        for rect, chart in zip(self.chart_rects(option.rect), charts):
            if rect.contains(QPointF(event.pos())):
                QToolTip.showText(event.globalPos(), chart['tooltip'], view)
                return True
        QToolTip.hideText()
        return True
