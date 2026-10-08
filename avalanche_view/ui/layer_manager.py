from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LayerTree(QTreeWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def dropEvent(self, event):
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if source and target and source.parent() is target.parent() and source.parent() is not None:
            group = source.parent()
            if group.text(0) == "MODEL":
                delta = group.indexOfChild(target) - group.indexOfChild(source)
                key = source.data(0, Qt.ItemDataRole.UserRole)
                if key and delta:
                    self.manager.move_requested.emit(key, delta)
                    event.acceptProposedAction()
                    return
        event.ignore()


class LayerManager(QWidget):
    layer_selected = pyqtSignal(str)
    visibility_changed = pyqtSignal(str, bool)
    remove_requested = pyqtSignal(str)
    move_requested = pyqtSignal(str, int)
    external_visibility = pyqtSignal(str, bool)
    external_removed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.grouped = False
        self.external = {}
        self._layers = []
        self.basemap_name = "Подложка: Рельеф"
        self.terrain_name = "Источник: HGT / HGT_M"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        caption = QLabel("LAYERS  ·  top layer is drawn last")
        caption.setWordWrap(True)
        caption.setObjectName("eyebrow")
        layout.addWidget(caption)
        self.tree = LayerTree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        for text, icon, tooltip, callback in (
            ("", QStyle.StandardPixmap.SP_ArrowUp, "Move layer up", lambda: self._move(-1)),
            ("", QStyle.StandardPixmap.SP_ArrowDown, "Move layer down", lambda: self._move(1)),
            ("Remove", None, "Remove selected layer", self._remove),
        ):
            button = QPushButton(text)
            if icon is not None:
                button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.tree.itemChanged.connect(self._changed)
        self.tree.currentItemChanged.connect(self._selected)

    def selected_id(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, layers, selected_id=None) -> None:
        self._layers = layers
        selected_id = selected_id or self.selected_id()
        with QSignalBlocker(self.tree):
            self.tree.clear()
            groups = {}
            if self.grouped:
                self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
                self.tree.setRootIsDecorated(True)
                for name in ("MODEL", "GIS", "BASEMAP", "TERRAIN"):
                    group = QTreeWidgetItem(self.tree, [name])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    group.setExpanded(True)
                    groups[name] = group
                QTreeWidgetItem(groups["BASEMAP"], [self.basemap_name]).setFlags(Qt.ItemFlag.ItemIsEnabled)
                QTreeWidgetItem(groups["TERRAIN"], [self.terrain_name]).setFlags(Qt.ItemFlag.ItemIsEnabled)
                for key, record in self.external.items():
                    item = QTreeWidgetItem(groups[record["group"]], [record["name"]])
                    item.setData(0, Qt.ItemDataRole.UserRole, key)
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, "external")
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Checked if record["visible"] else Qt.CheckState.Unchecked)
            for layer in layers:
                item = QTreeWidgetItem(groups.get(layer.group, self.tree), [layer.name])
                if self.grouped:
                    item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
                item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                )
                item.setToolTip(0, f"{layer.variable} · {layer.mode}\nOpacity: {layer.opacity:.0%}")
                if layer.id == selected_id:
                    self.tree.setCurrentItem(item)

    def _changed(self, item, column) -> None:
        if not item.data(0, Qt.ItemDataRole.UserRole):
            return
        if item.data(0, Qt.ItemDataRole.UserRole + 1) == "external":
            key = item.data(0, Qt.ItemDataRole.UserRole)
            visible = item.checkState(0) == Qt.CheckState.Checked
            self.external[key]["visible"] = visible
            self.external_visibility.emit(key, visible)
            return
        self.visibility_changed.emit(
            item.data(0, Qt.ItemDataRole.UserRole), item.checkState(0) == Qt.CheckState.Checked
        )

    def _selected(self, item, previous=None) -> None:
        if item and item.data(0, Qt.ItemDataRole.UserRole) and item.data(0, Qt.ItemDataRole.UserRole + 1) != "external":
            self.layer_selected.emit(item.data(0, Qt.ItemDataRole.UserRole))

    def _move(self, delta: int) -> None:
        if layer_id := self.selected_id():
            if layer_id in self.external:
                return
            self.move_requested.emit(layer_id, delta)

    def _remove(self) -> None:
        if layer_id := self.selected_id():
            if layer_id in self.external:
                self.external_removed.emit(layer_id)
                self.external.pop(layer_id)
                self.refresh(self._layers)
                return
            self.remove_requested.emit(layer_id)
