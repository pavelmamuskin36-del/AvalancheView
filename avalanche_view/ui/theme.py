import os
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette


def apply_theme(application, dark: bool) -> None:
    # The Windows offscreen platform cannot enumerate system fonts on its own.
    if not QFontDatabase.families() and os.name == "nt":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    application.setFont(QFont("Segoe UI", 10))
    application.setStyle("Fusion")
    palette = QPalette()
    colors = {
        "window": "#182332" if dark else "#edf2f7",
        "base": "#202e40" if dark else "#ffffff",
        "text": "#e1eaf3" if dark else "#20354c",
        "muted": "#a5b4c5" if dark else "#60738a",
        "border": "#344457" if dark else "#d3deea",
        "accent": "#23b9b2" if dark else "#087f8c",
    }
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Button):
        palette.setColor(role, QColor(colors["window"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["window"]))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(role, QColor(colors["text"]))
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["muted"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    application.setPalette(palette)
    application.setStyleSheet(f"""
        QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; }}
        QMainWindow, QDialog {{ background: {colors["window"]}; }}
        QDockWidget::title {{ background: {colors["window"]}; color: {colors["muted"]};
            padding: 8px 12px; font-weight: 600; }}
        QToolBar {{ spacing: 8px; padding: 5px; border: none; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {colors["base"]}; border: 1px solid {colors["border"]};
            border-radius: 5px; padding: 5px; min-height: 18px; }}
        QPushButton {{ border: 1px solid {colors["border"]}; border-radius: 5px;
            padding: 6px 10px; background: {colors["base"]}; }}
        QPushButton:hover {{ border-color: {colors["accent"]}; }}
        QPushButton:checked {{ background: {colors["accent"]}; color: white; }}
        QTreeView, QTableView {{ border: 1px solid {colors["border"]}; border-radius: 5px; }}
        QTreeView::item {{ padding: 5px 2px; }}
        QHeaderView::section {{ background: {colors["window"]}; border: none;
            padding: 6px; color: {colors["muted"]}; }}
        QLabel#brand {{ font-size: 21pt; font-weight: 700; color: {colors["text"]}; }}
        QLabel#eyebrow {{ font-size: 9pt; font-weight: 600; color: {colors["accent"]}; }}
        QLabel#datasetName {{ font-size: 11pt; font-weight: 600; }}
        QLabel#muted {{ color: {colors["muted"]}; font-size: 9pt; }}
        QLabel#error {{ color: #e16d59; }}
        QStatusBar {{ border-top: 1px solid {colors["border"]}; color: {colors["muted"]}; }}
        QSlider::groove:horizontal {{ height: 5px; border-radius: 2px; background: {colors["border"]}; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px;
            background: {colors["accent"]}; }}
        QSlider::sub-page:horizontal {{ background: {colors["accent"]}; border-radius: 2px; }}
        QTabWidget::pane {{ border: 1px solid {colors["border"]}; }}
        QTabBar::tab {{ padding: 7px 9px; }}
        QTabBar::tab:selected {{ color: {colors["accent"]}; }}
    """)
