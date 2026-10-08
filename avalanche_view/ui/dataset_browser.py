from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avalanche_view.data.snowpack import (
    SNOWPACK_BULK_VARIABLES,
    SNOWPACK_VERTICAL_DIM,
    is_snowpack_variable,
    snowpack_display_metadata,
)


class DatasetBrowser(QWidget):
    add_requested = pyqtSignal(str)
    info_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        self.file_label = QLabel("No dataset open")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("datasetName")
        layout.addWidget(self.file_label)
        self.summary = QLabel("Open .nc or wrfout* to begin")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search variables, descriptions, units…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Variable", "Units"])
        self.tree.setColumnWidth(0, 170)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)
        self.add_button = QPushButton("+ Add selected variable")
        self.add_button.setEnabled(False)
        layout.addWidget(self.add_button)
        self.search.textChanged.connect(self._filter)
        self.tree.itemDoubleClicked.connect(lambda item, _: self._add(item))
        self.add_button.clicked.connect(lambda: self._add(self.tree.currentItem()))
        self.tree.currentItemChanged.connect(self._selection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.dataset = None

    def _context_menu(self, position):
        if self.dataset is not None:
            menu = QMenu(self)
            menu.addAction("Информация о наборе данных", self.info_requested.emit)
            menu.exec(self.mapToGlobal(position))

    def set_dataset(self, dataset, language="ru") -> None:
        self.dataset = dataset
        self.tree.clear()
        self.file_label.setText(getattr(dataset, "name", dataset.path.name))
        self.file_label.setToolTip(str(dataset.path))
        self.summary.setText(
            f"{dataset.time_count} временных шагов · {len(dataset.variables)} переменных\n"
            f"{dataset.timestamps[0]} → {dataset.timestamps[-1]}"
        )
        dimensions = QTreeWidgetItem(self.tree, ["Dimensions"])
        for name, size in dataset.dimensions.items():
            QTreeWidgetItem(dimensions, [name, str(size)])
        times = QTreeWidgetItem(self.tree, ["Timestamps", str(dataset.time_count)])
        for timestamp in dataset.timestamps[:100]:
            QTreeWidgetItem(times, [timestamp])
        if dataset.time_count > 100:
            QTreeWidgetItem(times, ["Further timestamps available on timeline"])
        metadata = QTreeWidgetItem(self.tree, ["Metadata"])
        for name, value in dataset.metadata.items():
            text = str(value)
            child = QTreeWidgetItem(metadata, [name, text[:100]])
            child.setToolTip(0, f"{name}: {text}")
            child.setToolTip(1, text)
        groups = {
            key: QTreeWidgetItem(self.tree, [key])
            for key in (
                "Coordinates",
                "Data variables",
                "Derived variables",
            )
        }
        if SNOWPACK_VERTICAL_DIM in dataset.dimensions:
            for key in ("CRYOWRF / SNOWPACK bulk", "CRYOWRF / SNOWPACK layers"):
                groups[key] = QTreeWidgetItem(self.tree, [key])
        for variable in dataset.variables.values():
            group = (
                "Derived variables"
                if variable.derived
                else ("Coordinates" if variable.coordinate else "Data variables")
            )
            if SNOWPACK_VERTICAL_DIM in dataset.dimensions:
                if is_snowpack_variable(variable):
                    group = "CRYOWRF / SNOWPACK layers"
                elif variable.name in SNOWPACK_BULK_VARIABLES:
                    group = "CRYOWRF / SNOWPACK bulk"
            title, units = snowpack_display_metadata(variable, language)
            item = QTreeWidgetItem(groups[group], [variable.name, units])
            item.setData(0, Qt.ItemDataRole.UserRole, variable.name if variable.plottable else None)
            item.setData(
                0,
                Qt.ItemDataRole.UserRole + 1,
                f"{variable.name} {title} {variable.description} {units}".lower(),
            )
            dimensions_text = ", ".join(
                f"{d}={s}" for d, s in zip(variable.dimensions, variable.shape, strict=True)
            )
            item.setToolTip(
                0,
                f"{title}\n{dimensions_text}\nSource: {variable.description} [{variable.units}]\n"
                + (
                    "Double-click to add a layer"
                    if variable.plottable
                    else "Metadata / non-horizontal variable"
                ),
            )
        groups["Data variables"].setExpanded(True)
        groups["Derived variables"].setExpanded(True)
        if hasattr(dataset, "entries"):
            files = QTreeWidgetItem(self.tree, ["Файлы", str(len(dataset.entries))])
            for entry in dataset.entries:
                item = QTreeWidgetItem(files, [entry.path.name, str(len(entry.times))])
                item.setToolTip(0, str(entry.path))
                item.setCheckState(0, Qt.CheckState.Checked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            for group in groups.values():
                for index in range(group.childCount()):
                    item = group.child(index)
                    name = item.text(0)
                    available = dataset.availability(name)
                    item.setToolTip(
                        0,
                        item.toolTip(0)
                        + f"\nДоступно: {available} / {dataset.time_count} временных шагов",
                    )
                    if available != dataset.time_count:
                        item.setText(
                            1, f"{snowpack_display_metadata(dataset.variables[name], language)[1]} · {available}/{dataset.time_count}"
                        )
        self._filter(self.search.text())

    def set_language(self, language):
        """Refresh display titles/units without rebuilding the user's variable selection."""
        if self.dataset is None:
            return
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                name = item.text(0)
                if not item.data(0, Qt.ItemDataRole.UserRole + 1) or name not in self.dataset.variables:
                    continue
                info = self.dataset.variables[name]
                title, units = snowpack_display_metadata(info, language)
                suffix = item.text(1).partition(" · ")[2]
                item.setText(1, units + (" · " + suffix if suffix else ""))
                item.setToolTip(0, title + "\n" + item.toolTip(0).partition("\n")[2])
                item.setData(0, Qt.ItemDataRole.UserRole + 1,
                             f"{name} {title} {info.description} {units}".lower())
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group.text(0) not in {"Coordinates", "Data variables", "Derived variables",
                                      "CRYOWRF / SNOWPACK bulk", "CRYOWRF / SNOWPACK layers",
                                      "Координаты", "Переменные", "Производные величины"}:
                group.setHidden(bool(text))
                continue
            visible = False
            for child_index in range(group.childCount()):
                child = group.child(child_index)
                haystack = child.data(0, Qt.ItemDataRole.UserRole + 1) or child.text(0).lower()
                matches = not text or text in haystack
                child.setHidden(not matches)
                visible |= matches
            group.setHidden(not visible)
            if text:
                group.setExpanded(True)

    def _selection(self, item, previous=None) -> None:
        self.add_button.setEnabled(bool(item and item.data(0, Qt.ItemDataRole.UserRole)))

    def _add(self, item) -> None:
        if item:
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:
                self.add_requested.emit(name)
