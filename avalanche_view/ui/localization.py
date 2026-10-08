"""UI text catalog; variable names, units and metadata remain source-authentic."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QTreeWidget

CATALOG = {
    "Snow cover": "Снежный покров",
    "SNOWPACK profile": "Профиль SNOWPACK",
    "Load demo": "Демоданные",
    "Load demo data": "Загрузить демоданные",
    "No dataset open": "Нет открытого набора данных",
    "Open .nc or wrfout* to begin": "Откройте NetCDF, WRF или met_em",
    "Search variables, descriptions, units…": "Поиск переменных, описаний, единиц…",
    "Variable": "Переменная",
    "Units": "Единицы",
    "Value": "Значение",
    "+ Add selected variable": "+ Добавить переменную",
    "Dimensions": "Размерности",
    "Timestamps": "Временные шаги",
    "Metadata": "Метаданные",
    "Coordinates": "Координаты",
    "Data variables": "Переменные",
    "Derived variables": "Производные величины",
    "LAYERS  ·  top layer is drawn last": "СЛОИ · верхний слой рисуется последним",
    "Remove": "Удалить",
    "Select a layer to edit its appearance": "Выберите слой для настройки",
    "Layer name": "Название слоя",
    "Variable units": "Единицы",
    "Render mode": "Отображение",
    "Colormap": "Цветовая шкала",
    "Automatic range per frame": "Диапазон по текущему шагу",
    "Minimum": "Минимум",
    "Maximum": "Максимум",
    "Opacity": "Непрозрачность",
    "Contour levels": "Число изолиний",
    "Vertical index": "Вертикальный уровень",
    "Vector spacing": "Шаг векторов",
    "Smooth display (3×3 filter)": "Сглаживание отображения (3×3)",
    "Show colorbar": "Показывать шкалу",
    "Changes apply automatically.\nUse a fixed range to compare timesteps.": "Настройки применяются автоматически.\nДля сравнения шагов закрепите диапазон.",
    "Heatmap": "Заливка",
    "Filled contours": "Заливка по уровням",
    "Contour lines": "Изолинии",
    "Wind vectors": "Стрелки ветра",
    "Wind barbs": "Метеорологические значки",
    "Hillshade": "Отмывка",
    "Categorical classes": "Категории",
    "Native grid": "Исходная сетка",
    "Fill and contours": "Заливка + изолинии",
    "Streamlines": "Линии тока",
    "Wind speed and arrows": "Скорость + стрелки",
    "Wind speed and barbs": "Скорость + значки",
    "Click on the map to inspect a grid cell": "Выберите ячейку на карте",
    "Point values": "Значения в точке",
    "Speed": "Скорость",
    "No time axis": "Нет временной шкалы",
    "Dark theme": "Тёмная тема",
    "&Help": "&Справка",
    "Quick start": "Начало работы",
    "About AvalancheView": "О программе",
}


def translate_window(window, language):
    reverse = {value: key for key, value in CATALOG.items()}

    def text(value):
        original = reverse.get(value, value)
        return CATALOG.get(original, original) if language == "ru" else original

    for widget in window.findChildren(QLabel) + window.findChildren(QAbstractButton):
        widget.setText(text(widget.text()))
    for widget in window.findChildren(QLineEdit):
        widget.setPlaceholderText(text(widget.placeholderText()))
    for action in window.findChildren(QAction):
        action.setText(text(action.text()))
    mode = window.properties.mode
    mode.blockSignals(True)
    for index in range(mode.count()):
        original = mode.itemData(index) or reverse.get(mode.itemText(index), mode.itemText(index))
        mode.setItemData(index, original)
        mode.setItemText(index, text(original))
    mode.blockSignals(False)
    for tree in window.findChildren(QTreeWidget):
        for column in range(tree.columnCount()):
            tree.headerItem().setText(column, text(tree.headerItem().text(column)))
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if not item.data(0, Qt.ItemDataRole.UserRole):
                item.setText(0, text(item.text(0)))
    window.settings.setValue("language", language)
    browser = getattr(window, "browser", None)
    if browser is not None:
        browser.set_language(language)
    if getattr(window, "dataset", None) is not None and getattr(window, "selected_point", None) is not None:
        window._snow_inspection_key = None
        window._refresh_inspector()
