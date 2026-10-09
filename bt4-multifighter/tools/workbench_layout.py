"""Scrollable native panels that remain reachable on small/HiDPI displays."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame


def scroll_panel(body):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(body)
    return scroll


def fit_window(window, width, height):
    available = window.screen().availableGeometry()
    window.resize(min(width, max(320, available.width() - 32)),
                  min(height, max(240, available.height() - 64)))


def scroll_dialog(dialog):
    """Keep the final confirmation row visible while the form scrolls."""
    outer = dialog.layout()
    body = QWidget()
    content = QVBoxLayout(body)
    content.setContentsMargins(0, 0, 0, 0)
    while outer.count() > 1:
        item = outer.takeAt(0)
        if item.widget():
            content.addWidget(item.widget())
        elif item.layout():
            content.addLayout(item.layout())
        else:
            content.addItem(item)
    dialog.form_scroll = scroll_panel(body)
    outer.insertWidget(0, dialog.form_scroll, 1)
    fit_window(dialog, dialog.width(), dialog.height())
