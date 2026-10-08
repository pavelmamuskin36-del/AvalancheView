from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QWidget


class TimelineWidget(QWidget):
    timestep_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.timestamps: list[str] = []
        self.gaps = set()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._advance)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        self.first = self._button(QStyle.StandardPixmap.SP_MediaSkipBackward, "First timestep")
        self.previous = self._button(
            QStyle.StandardPixmap.SP_MediaSeekBackward, "Previous timestep"
        )
        self.play = self._button(QStyle.StandardPixmap.SP_MediaPlay, "Play / Pause")
        self.play.setCheckable(True)
        self.next = self._button(QStyle.StandardPixmap.SP_MediaSeekForward, "Next timestep")
        self.last = self._button(QStyle.StandardPixmap.SP_MediaSkipForward, "Last timestep")
        for button in (self.first, self.previous, self.play, self.next, self.last):
            layout.addWidget(button)
        self.label = QLabel("No time axis")
        self.label.setMinimumWidth(195)
        layout.addWidget(self.label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        layout.addWidget(self.slider, 1)
        self.step_label = QLabel("—")
        layout.addWidget(self.step_label)
        layout.addWidget(QLabel("Speed"))
        self.speed = QComboBox()
        self.speed.addItems(["0.25x", "0.5x", "1x", "2x", "4x"])
        self.speed.setCurrentText("1x")
        layout.addWidget(self.speed)
        self.first.clicked.connect(lambda: self.slider.setValue(0))
        self.previous.clicked.connect(lambda: self.slider.setValue(self.slider.value() - 1))
        self.next.clicked.connect(lambda: self.slider.setValue(self.slider.value() + 1))
        self.last.clicked.connect(lambda: self.slider.setValue(self.slider.maximum()))
        self.play.toggled.connect(self._toggle_play)
        self.slider.valueChanged.connect(self._changed)
        self.speed.currentTextChanged.connect(self._speed)
        self.setEnabled(False)

    def _button(self, icon, tooltip):
        button = QPushButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setFixedWidth(32)
        return button

    def set_timestamps(self, timestamps: list[str], gaps=()) -> None:
        self.pause()
        self.timestamps = timestamps
        self.gaps = set(gaps)
        with QSignalBlocker(self.slider):
            self.slider.setRange(0, max(0, len(timestamps) - 1))
            self.slider.setValue(0)
        self.setEnabled(bool(timestamps))
        self.play.setEnabled(len(timestamps) > 1)
        self._update_label(0)

    def _update_label(self, index: int) -> None:
        self.label.setText(self.timestamps[index] if self.timestamps else "No time axis")
        self.step_label.setText(f"{index + 1} / {len(self.timestamps)}" if self.timestamps else "—")
        gap = index in self.gaps
        self.label.setToolTip(
            "Перед этим шагом есть пропуск относительно обычного интервала серии" if gap else ""
        )
        self.step_label.setText(self.step_label.text() + (" · пропуск" if gap else ""))

    def _changed(self, index: int) -> None:
        self._update_label(index)
        self.timestep_changed.emit(index)

    def _toggle_play(self, playing: bool) -> None:
        if playing:
            self.timer.start()
        else:
            self.timer.stop()
        icon = (
            QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play.setIcon(self.style().standardIcon(icon))

    def pause(self) -> None:
        self.play.setChecked(False)
        self.timer.stop()

    def _speed(self, value: str) -> None:
        self.timer.setInterval(round(1000 / float(value[:-1])))

    def _advance(self) -> None:
        if len(self.timestamps) > 1:
            self.slider.setValue((self.slider.value() + 1) % len(self.timestamps))
