from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout


class SeriesSelectionDialog(QDialog):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Найденные данные модели")
        self.resize(700, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Выберите серию. Разные domains и несовместимые сетки показаны отдельно.")
        )
        self.list = QListWidget()
        for group in groups:
            self.list.addItem(group.label)
        self.list.setCurrentRow(0)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(buttons)

    @property
    def selected_index(self):
        return self.list.currentRow()
