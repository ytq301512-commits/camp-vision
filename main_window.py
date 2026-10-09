from __future__ import annotations

from pathlib import Path
import time

from PySide6.QtCore import QRect, QSettings, QThreadPool, QTimer, Qt
from PySide6.QtGui import QColor, QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .capture import (
    capture_region,
    load_image,
    qt_capture_scales,
    qt_rect_to_capture_rect,
)
from .matcher import CharacterMatcher
from .card_matcher import CardImageMatcher
from .models import Match, OcrDetection, load_roster
from .ocr import RapidOcrEngine
from .overlay import RegionSelector, ResultOverlay
from .roster_widget import RosterWidget
from .workers import CardResultStabilizer, RecognitionTask, merge_recognition_results


class ResolutionDialog(QDialog):
    """Choose the physical display resolution used for coordinate conversion."""

    def __init__(
        self,
        current: tuple[int, int] | None,
        detected: list[tuple[int, int]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("屏幕分辨率")
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        self.preset = QComboBox()
        self.preset.addItem("自动（使用 Windows DPI）", None)
        choices: list[tuple[int, int]] = []
        for value in detected + [(1920, 1080), (2560, 1440), (2560, 1600), (3840, 2160)]:
            if value not in choices:
                choices.append(value)
                self.preset.addItem(f"{value[0]} × {value[1]}", value)
        self.preset.addItem("自定义…", "custom")
        layout.addRow("使用分辨率", self.preset)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 16000)
        self.width_spin.setSingleStep(10)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(240, 16000)
        self.height_spin.setSingleStep(10)
        self.height_spin.setSuffix(" px")
        layout.addRow("宽度", self.width_spin)
        layout.addRow("高度", self.height_spin)

        hint = QLabel("填写显示器的实际像素分辨率，例如 2560 × 1600。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if current is None:
            self.preset.setCurrentIndex(0)
            self.width_spin.setValue(1920)
            self.height_spin.setValue(1080)
        elif current in choices:
            self.preset.setCurrentText(f"{current[0]} × {current[1]}")
            self.width_spin.setValue(current[0])
            self.height_spin.setValue(current[1])
        else:
            self.preset.setCurrentText("自定义…")
            self.width_spin.setValue(current[0])
            self.height_spin.setValue(current[1])
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self._preset_changed(self.preset.currentIndex())

    def _preset_changed(self, _index: int) -> None:
        value = self.preset.currentData()
        custom = value == "custom"
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)
        if not custom and isinstance(value, tuple):
            self.width_spin.setValue(value[0])
            self.height_spin.setValue(value[1])

    def selected_resolution(self) -> tuple[int, int] | None:
        value = self.preset.currentData()
        if value is None:
            return None
        return self.width_spin.value(), self.height_spin.value()


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self.roster_path = project_root / "data" / "roster.json"
        self.settings = QSettings("CampVision", "CampVision")
        self.save_config = self._read_bool_setting("save_config", True)
        self.screen_resolution = self._read_resolution_setting()
        self.region = QRect()
        self.running = False
        self.busy = False
        self._last_card_scan = 0.0
        self._last_card_matches: list[Match] = []
        self._card_stabilizer = CardResultStabilizer()
        self._active_task: RecognitionTask | None = None
        self.gpu_available = (
            RapidOcrEngine.hardware_acceleration_available()
            or CardImageMatcher.hardware_acceleration_available()
        )
        saved_gpu = self.settings.value("gpu_acceleration", self.gpu_available) if self.save_config else self.gpu_available
        if isinstance(saved_gpu, str):
            saved_gpu = saved_gpu.lower() in {"1", "true", "yes"}
        self.gpu_enabled = bool(saved_gpu) and self.gpu_available
        self.engine = RapidOcrEngine(use_gpu=self.gpu_enabled)
        self.card_matcher = CardImageMatcher(load_roster(self.roster_path), use_gpu=self.gpu_enabled)
        self.thread_pool = QThreadPool.globalInstance()
        self.overlay = ResultOverlay()
        self.overlay.set_resolution(self.screen_resolution)
        self.selector: RegionSelector | None = None

        self.setWindowTitle("阵营识别 · Camp Vision")
        self.setMinimumSize(920, 640)
        self.resize(1100, 720)
        self._build_ui()
        self._restore_region()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan_once)
        self.roster_widget.changed.connect(self._on_roster_changed)

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 24, 20, 20)
        title = QLabel("阵营识别")
        title.setObjectName("appTitle")
        subtitle = QLabel("CAMP VISION")
        subtitle.setObjectName("appSubtitle")
        side_layout.addWidget(title)
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(28)

        self.monitor_nav = QPushButton("实时识别")
        self.roster_nav = QPushButton("人物库")
        for button in (self.monitor_nav, self.roster_nav):
            button.setCheckable(True)
            button.setObjectName("navButton")
            side_layout.addWidget(button)
        self.monitor_nav.setChecked(True)
        side_layout.addStretch()
        version = QLabel("v0.1 · 本地离线 OCR")
        version.setObjectName("muted")
        side_layout.addWidget(version)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 24)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_monitor_page())
        self.roster_widget = RosterWidget(self.roster_path)
        self.pages.addWidget(self._build_roster_page())
        content_layout.addWidget(self.pages)

        self.monitor_nav.clicked.connect(lambda: self._show_page(0))
        self.roster_nav.clicked.connect(lambda: self._show_page(1))
        outer.addWidget(sidebar)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)

    def _build_monitor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("实时文字识别")
        heading.setObjectName("pageTitle")
        description = QLabel("只识别你点击“框选范围”后拖出的区域；建议框住完整卡面和底部名称，软件会同时进行卡图识别与 OCR，框外内容不会读取。")
        description.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addSpacing(18)

        controls = QFrame()
        controls.setObjectName("panel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(18, 14, 18, 14)
        controls_layout.setSpacing(10)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.region_label = QLabel("尚未选择识别范围")
        self.region_label.setObjectName("regionLabel")
        select_button = QPushButton("框选范围")
        image_button = QPushButton("识别图片")
        self.start_button = QPushButton("开始识别（当前范围）")
        self.start_button.setObjectName("primaryButton")
        self.interval = QSpinBox()
        self.interval.setRange(50, 5000)
        self.interval.setSingleStep(50)
        saved_interval = self.settings.value("interval_ms", 100) if self.save_config else 100
        try:
            saved_interval = int(saved_interval)
        except (TypeError, ValueError):
            saved_interval = 100
        self.interval.setValue(max(50, min(saved_interval, 5000)))
        self.interval.setSuffix(" ms")
        self.interval.setToolTip("连续识别间隔，可设置 50ms")
        self.interval.valueChanged.connect(self._interval_changed)
        self.card_interval = QSpinBox()
        self.card_interval.setRange(150, 10000)
        self.card_interval.setSingleStep(50)
        saved_card_interval = self.settings.value("card_interval_ms", 300) if self.save_config else 300
        try:
            saved_card_interval = int(saved_card_interval)
        except (TypeError, ValueError):
            saved_card_interval = 300
        self.card_interval.setValue(max(150, min(saved_card_interval, 10000)))
        self.card_interval.setSuffix(" ms")
        self.card_interval.setToolTip("卡图匹配的最短间隔；OCR 仍按上面的识别间隔运行")
        self.card_interval.valueChanged.connect(self._card_interval_changed)
        self.ocr_checkbox = QCheckBox("OCR 识别")
        self.ocr_checkbox.setChecked(self._read_bool_setting("use_ocr", True))
        self.ocr_checkbox.setToolTip("使用文字识别通道")
        self.card_checkbox = QCheckBox("卡图识别")
        self.card_checkbox.setChecked(self._read_bool_setting("use_card", True))
        self.card_checkbox.setToolTip("使用完整卡面图片匹配通道")
        self.ocr_checkbox.stateChanged.connect(self._recognition_mode_changed)
        self.card_checkbox.stateChanged.connect(self._recognition_mode_changed)
        self.gpu_checkbox = QCheckBox("硬件加速")
        self.gpu_checkbox.setChecked(self.gpu_enabled)
        self.gpu_checkbox.setEnabled(self.gpu_available)
        self.gpu_checkbox.setToolTip(
            "自动选择更快的可用后端：OCR 使用 CUDA/DirectML，卡图使用 OpenCL"
            if self.gpu_available
            else "未检测到可用 GPU 执行提供程序，当前使用 CPU"
        )
        self.gpu_checkbox.stateChanged.connect(self._toggle_gpu)
        self.save_checkbox = QCheckBox("保存配置")
        self.save_checkbox.setChecked(self.save_config)
        self.save_checkbox.setToolTip("保存识别范围、分辨率、识别间隔和 GPU 加速设置")
        self.save_checkbox.stateChanged.connect(self._toggle_save_config)
        self.resolution_button = QPushButton()
        self.resolution_button.setMinimumWidth(120)
        self.resolution_button.setToolTip("设置显示器实际像素分辨率，用于把框选坐标换算为截图坐标")
        self._update_resolution_button()
        self.resolution_button.clicked.connect(self._edit_resolution)
        select_button.clicked.connect(self.select_region)
        image_button.clicked.connect(self.recognize_image)
        self.start_button.clicked.connect(self.toggle_monitoring)
        top_row.addWidget(self.region_label, 1)
        top_row.addWidget(select_button)
        top_row.addWidget(image_button)
        mode_label = QLabel("识别通道")
        mode_label.setObjectName("muted")
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.ocr_checkbox)
        mode_row.addWidget(self.card_checkbox)
        mode_row.addSpacing(14)
        mode_row.addWidget(QLabel("间隔"))
        mode_row.addWidget(self.interval)
        mode_row.addSpacing(8)
        mode_row.addWidget(QLabel("卡图间隔"))
        mode_row.addWidget(self.card_interval)
        mode_row.addStretch()
        action_row.addWidget(self.gpu_checkbox)
        action_row.addWidget(self.save_checkbox)
        action_row.addWidget(self.resolution_button)
        action_row.addStretch()
        action_row.addWidget(self.start_button)
        controls_layout.addLayout(top_row)
        controls_layout.addLayout(mode_row)
        controls_layout.addLayout(action_row)
        layout.addWidget(controls)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setText(self._hardware_status("就绪"))
        layout.addWidget(self.status_label)

        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels(["识别文字", "匹配人物", "阵营", "OCR 置信度", "匹配度"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setAlternatingRowColors(True)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.results, 1)
        return page

    def _hardware_status(self, prefix: str) -> str:
        if isinstance(self.engine, RapidOcrEngine):
            mode_by_provider = {
                "CUDAExecutionProvider": "CUDA GPU",
                "DmlExecutionProvider": "DirectML GPU",
            }
            if self.engine.use_gpu and self.engine._engine is None:
                mode = "GPU 加速待命"
            else:
                mode = mode_by_provider.get(self.engine.active_provider, "CPU")
        else:
            mode = "CPU"
        card_mode = f" + 卡图 {self.card_matcher.acceleration_backend}" if self.card_matcher.use_gpu else ""
        return f"{prefix} · OCR 硬件：{mode}{card_mode}"

    def _read_bool_setting(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _read_resolution_setting(self) -> tuple[int, int] | None:
        if not self.save_config:
            return None
        width = self.settings.value("screen_resolution_width")
        height = self.settings.value("screen_resolution_height")
        try:
            width, height = int(width), int(height)
        except (TypeError, ValueError):
            return None
        if width < 320 or height < 240:
            return None
        return width, height

    def _detected_resolutions(self) -> list[tuple[int, int]]:
        from PySide6.QtGui import QGuiApplication

        result: list[tuple[int, int]] = []
        app = QGuiApplication.instance()
        if app is None:
            return result
        for screen in app.screens():
            geometry = screen.geometry()
            scale = max(float(screen.devicePixelRatio()), 1.0)
            value = (round(geometry.width() * scale), round(geometry.height() * scale))
            if value not in result:
                result.append(value)
        return result

    def _update_resolution_button(self) -> None:
        if self.screen_resolution is None:
            self.resolution_button.setText("分辨率：自动")
        else:
            self.resolution_button.setText(
                f"分辨率：{self.screen_resolution[0]}×{self.screen_resolution[1]}"
            )

    def _edit_resolution(self) -> None:
        dialog = ResolutionDialog(self.screen_resolution, self._detected_resolutions(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.screen_resolution = dialog.selected_resolution()
        self.overlay.set_resolution(self.screen_resolution)
        self._update_resolution_button()
        if self.save_config:
            if self.screen_resolution is None:
                self.settings.remove("screen_resolution_width")
                self.settings.remove("screen_resolution_height")
            else:
                self.settings.setValue("screen_resolution_width", self.screen_resolution[0])
                self.settings.setValue("screen_resolution_height", self.screen_resolution[1])
        if not self.region.isEmpty():
            self.set_region(self.region)
        mode = "自动 DPI" if self.screen_resolution is None else f"{self.screen_resolution[0]}×{self.screen_resolution[1]}"
        self.status_label.setText(self._hardware_status(f"分辨率换算已更新：{mode}"))

    def _interval_changed(self, value: int) -> None:
        # QSpinBox does not emit valueChanged when the selected value stays
        # the same. Keep the timer synchronized even when callers set the
        # current value explicitly (for example after restoring settings).
        if self.timer.isActive() and self.timer.interval() != value:
            self.timer.setInterval(value)
        elif self.timer.isActive():
            self.timer.start(value)
        if self.save_config:
            self.settings.setValue("interval_ms", int(value))

    def _card_interval_changed(self, value: int) -> None:
        if self.save_config:
            self.settings.setValue("card_interval_ms", int(value))

    def _recognition_mode_changed(self, _state: int) -> None:
        if not self.ocr_checkbox.isChecked() and not self.card_checkbox.isChecked():
            sender = self.sender()
            if sender is not None:
                sender.blockSignals(True)
                sender.setChecked(True)
                sender.blockSignals(False)
            return
        if self.save_config:
            self.settings.setValue("use_ocr", self.ocr_checkbox.isChecked())
            self.settings.setValue("use_card", self.card_checkbox.isChecked())
        self.status_label.setText(self._hardware_status("识别通道设置已更新"))

    def _toggle_save_config(self, state: int) -> None:
        self.save_config = bool(state)
        self.settings.setValue("save_config", self.save_config)
        if self.save_config:
            self.settings.setValue("interval_ms", self.interval.value())
            self.settings.setValue("card_interval_ms", self.card_interval.value())
            self.settings.setValue("gpu_acceleration", self.gpu_enabled)
            self.settings.setValue("use_ocr", self.ocr_checkbox.isChecked())
            self.settings.setValue("use_card", self.card_checkbox.isChecked())
            if self.screen_resolution is not None:
                self.settings.setValue("screen_resolution_width", self.screen_resolution[0])
                self.settings.setValue("screen_resolution_height", self.screen_resolution[1])
            if not self.region.isEmpty():
                self.settings.setValue(
                    "region",
                    [self.region.x(), self.region.y(), self.region.width(), self.region.height()],
                )
        else:
            for key in (
                "interval_ms",
                "card_interval_ms",
                "gpu_acceleration",
                "use_ocr",
                "use_card",
                "region",
                "screen_resolution_width",
                "screen_resolution_height",
            ):
                self.settings.remove(key)
        self.status_label.setText(
            self._hardware_status("配置保存已开启" if self.save_config else "配置保存已关闭")
        )

    def _toggle_gpu(self, state: int) -> None:
        if self.busy:
            return
        enabled = bool(state) and self.gpu_available
        self.gpu_enabled = enabled
        if isinstance(self.engine, RapidOcrEngine):
            self.engine.set_gpu_enabled(enabled)
        self.card_matcher.set_gpu_enabled(enabled)
        if self.save_config:
            self.settings.setValue("gpu_acceleration", enabled)
        self.status_label.setText(self._hardware_status("硬件加速设置已更新"))

    def _build_roster_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("人物库")
        heading.setObjectName("pageTitle")
        description = QLabel("人物名和别名用于 OCR 匹配；别名可填写常见简称或容易误识别的写法。")
        description.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addSpacing(18)
        layout.addWidget(self.roster_widget)
        return page

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.monitor_nav.setChecked(index == 0)
        self.roster_nav.setChecked(index == 1)

    def _restore_region(self) -> None:
        if not self.save_config:
            return
        values = self.settings.value("region")
        if isinstance(values, list) and len(values) == 4:
            self.set_region(QRect(*(int(value) for value in values)))

    def select_region(self) -> None:
        was_running = self.running
        if was_running:
            self.stop_monitoring()
        self.hide()
        self.overlay.hide()
        QTimer.singleShot(150, lambda: self._show_selector(was_running))

    def _show_selector(self, resume: bool) -> None:
        self.selector = RegionSelector()

        def selected(rect: QRect) -> None:
            self.set_region(rect)
            self.show()
            self.raise_()
            if resume:
                self.start_monitoring()

        def cancelled() -> None:
            self.show()
            self.raise_()
            if resume:
                self.start_monitoring()

        self.selector.selected.connect(selected)
        self.selector.cancelled.connect(cancelled)
        self.selector.show()

    def set_region(self, rect: QRect) -> None:
        self.region = QRect(rect)
        physical = qt_rect_to_capture_rect(rect, resolution=self.screen_resolution)
        x_scale, y_scale = qt_capture_scales(rect, self.screen_resolution)
        self.region_label.setText(
            f"框选：{rect.x()}, {rect.y()} · {rect.width()} × {rect.height()}"
            f"（截图：{physical.x()}, {physical.y()} · {physical.width()} × {physical.height()}"
            f"，缩放 {x_scale:.0%} / {y_scale:.0%}）"
        )
        if self.save_config:
            self.settings.setValue("region", [rect.x(), rect.y(), rect.width(), rect.height()])

    def toggle_monitoring(self) -> None:
        if self.running:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self) -> None:
        if self.region.isEmpty():
            QMessageBox.information(self, "需要识别范围", "请先点击“框选范围”，圈出人物名称所在区域。")
            return
        if not self.ocr_checkbox.isChecked() and not self.card_checkbox.isChecked():
            QMessageBox.information(self, "请选择识别通道", "请至少开启 OCR 识别或卡图识别其中一个通道。")
            return
        if not load_roster(self.roster_path):
            QMessageBox.information(self, "人物库为空", "请先在人物库中添加人物和对应阵营。")
            return
        self.running = True
        self.start_button.setText("停止识别")
        self.start_button.setProperty("running", True)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.timer.start(self.interval.value())
        self.status_label.setText(self._hardware_status("正在监控所选区域…"))
        self.scan_once()

    def stop_monitoring(self) -> None:
        self.running = False
        self.timer.stop()
        self._last_card_matches = []
        self._card_stabilizer.reset()
        self.overlay.clear()
        self.start_button.setText("开始识别（当前范围）")
        self.start_button.setProperty("running", False)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.status_label.setText(self._hardware_status("已停止"))

    def scan_once(self) -> None:
        if self.busy or self.region.isEmpty():
            return
        region = QRect(self.region)
        now = time.monotonic()
        card_due = self.card_checkbox.isChecked() and (
            now - self._last_card_scan >= self.card_interval.value() / 1000
        )
        if card_due:
            self._last_card_scan = now
        self._submit(lambda: capture_region(region, self.screen_resolution), region, use_card=card_due)

    def recognize_image(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "选择测试图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if filename:
            self._submit(lambda: load_image(Path(filename)), None, use_card=self.card_checkbox.isChecked())

    def _submit(self, supplier, region: QRect | None, use_card: bool | None = None) -> None:  # type: ignore[no-untyped-def]
        if self.busy:
            return
        try:
            matcher = CharacterMatcher(load_roster(self.roster_path))
        except Exception as exc:
            QMessageBox.warning(self, "人物库错误", str(exc))
            return
        self.busy = True
        self.gpu_checkbox.setEnabled(False)
        self.ocr_checkbox.setEnabled(False)
        self.card_checkbox.setEnabled(False)
        self.status_label.setText(self._hardware_status("正在识别文字…"))
        task = RecognitionTask(
            supplier,
            self.engine,
            matcher,
            self.card_matcher,
            use_ocr=self.ocr_checkbox.isChecked(),
            use_card=self.card_checkbox.isChecked() if use_card is None else use_card,
        )
        # Keep a Python reference until the queued signal is delivered. Without
        # this, QRunnable can be collected while the worker is still running.
        self._active_task = task
        task.signals.finished.connect(
            lambda detections, matches: self._recognition_done(
                detections, matches, region, bool(task.use_card)
            )
        )
        task.signals.failed.connect(self._recognition_failed)
        self.thread_pool.start(task)

    def _recognition_done(
        self,
        detections: list[OcrDetection],
        matches: list[Match],
        region: QRect | None,
        card_scan: bool = False,
    ) -> None:
        self.busy = False
        self._active_task = None
        self.gpu_checkbox.setEnabled(self.gpu_available)
        self.ocr_checkbox.setEnabled(True)
        self.card_checkbox.setEnabled(True)
        if isinstance(self.engine, RapidOcrEngine) and self.engine.use_gpu != self.gpu_enabled:
            self.gpu_enabled = self.engine.use_gpu
            self.gpu_checkbox.blockSignals(True)
            self.gpu_checkbox.setChecked(self.gpu_enabled)
            self.gpu_checkbox.blockSignals(False)
        if card_scan:
            self._last_card_matches = self._card_stabilizer.update(
                [item for item in matches if item.source == "card"]
            )
        elif not self.card_checkbox.isChecked():
            self._last_card_matches = []
            self._card_stabilizer.reset()
        elif self._last_card_matches:
            # Card matching is intentionally throttled independently from OCR.
            # Keep the last stable card result visible between card scans so a
            # fast OCR tick cannot make the camp labels disappear or jump.
            detections, matches = merge_recognition_results(
                detections,
                matches,
                self._last_card_matches,
            )

        self._show_results(detections, matches)
        if region is not None and self.running:
            self.overlay.set_results(region, matches)
        if detections:
            self.status_label.setText(self._hardware_status(f"当前框选区域识别到 {len(detections)} 段文字，匹配 {len(matches)} 个人物"))
        else:
            self.status_label.setText(self._hardware_status("当前框选区域未识别到文字，请重新框选底部卡牌名称区域"))

    @staticmethod
    def _same_result_area(left: Match, right: Match) -> bool:
        """Detect a cached card result already represented by OCR."""
        if left.character.name != right.character.name:
            return False
        a = left.detection.box
        b = right.detection.box
        x1, y1 = max(a.left, b.left), max(a.top, b.top)
        x2, y2 = min(a.right, b.right), min(a.bottom, b.bottom)
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        if not intersection:
            return False
        union = a.width * a.height + b.width * b.height - intersection
        return bool(union and intersection / union >= 0.10)

    def _recognition_failed(self, message: str) -> None:
        self.busy = False
        self._active_task = None
        self.gpu_checkbox.setEnabled(self.gpu_available)
        self.ocr_checkbox.setEnabled(True)
        self.card_checkbox.setEnabled(True)
        self.status_label.setText(self._hardware_status(f"识别失败：{message}"))
        if self.running:
            self.stop_monitoring()
        QMessageBox.warning(self, "识别失败", message)

    def _show_results(self, detections: list[OcrDetection], matches: list[Match]) -> None:
        by_detection = {id(match.detection): match for match in matches}
        self.results.setRowCount(len(detections))
        for row, detection in enumerate(detections):
            match = by_detection.get(id(detection))
            values = [
                detection.text,
                match.character.name if match else "未匹配",
                match.character.camp if match else "—",
                f"{detection.confidence:.0%}",
                f"{match.score:.0%}" if match else "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if match and column == 2:
                    item.setForeground(QColor(match.character.color))
                self.results.setItem(row, column, item)
        self.results.resizeColumnsToContents()

    def _on_roster_changed(self, characters) -> None:  # type: ignore[no-untyped-def]
        self.card_matcher = CardImageMatcher(list(characters), use_gpu=self.gpu_enabled)
        self.status_label.setText(f"人物库已更新：{len(characters)} 人")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.timer.stop()
        self.overlay.close()
        event.accept()
