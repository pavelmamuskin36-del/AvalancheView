from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget


class PlotsPanel(QWidget):
    """Persistent dock content; closing a dock preserves its plots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.setMinimumHeight(280)
        self.hint = QLabel("Выберите точку на карте и нажмите «Временной ряд» в инспекторе.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_plot)
        layout.addWidget(self.tabs)

    def add_plot(self, dialog, title):
        dialog.canvas.setMinimumSize(350, 150)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        self.tabs.setCurrentIndex(self.tabs.addTab(dialog, title))
        self.hint.hide()

    def remove_plot(self, index):
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        widget.deleteLater()
        self.hint.setVisible(self.tabs.count() == 0)
