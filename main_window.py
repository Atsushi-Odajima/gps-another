from __future__ import annotations

import json
from typing import Sequence

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import CONFIG, resource_path
from device_manager import DeviceManager, DeviceStatus
from location_sender import LocationSender, MockLocationSender
from route_interpolator import Coordinate, TransmissionPlan, build_transmission_plan
from route_service import RouteMode, RouteResult, RouteService, RouteServiceError, mode_for_speed


class MapBridge(QObject):
    map_clicked = Signal(float, float)

    @Slot(float, float)
    def handleMapClick(self, latitude: float, longitude: float) -> None:
        self.map_clicked.emit(latitude, longitude)


class RouteFetchThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, points: Sequence[Coordinate], speed_kmh: int) -> None:
        super().__init__()
        self.points = list(points)
        self.speed_kmh = speed_kmh

    def run(self) -> None:
        try:
            result = RouteService(CONFIG).fetch_route(self.points, self.speed_kmh)
        except (RouteServiceError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"ルート取得中に予期しないエラーが発生しました: {exc}")
            return
        self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(
        self,
        device_manager: DeviceManager | None = None,
        location_sender: LocationSender | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("gps-another")
        icon_path = resource_path("assets/app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(980, 640)

        self.device_manager = device_manager or DeviceManager()
        self.location_sender = location_sender or MockLocationSender()
        self.points: list[Coordinate] = []
        self.route_coordinates: list[Coordinate] = []
        self.route_mode: RouteMode | None = None
        self.transmission_plan: TransmissionPlan | None = None
        self.current_send_index = 0
        self.route_thread: RouteFetchThread | None = None

        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self._send_next_location)

        self.bridge = MapBridge()
        self.bridge.map_clicked.connect(self._add_point_from_map)

        self._build_ui()
        self._load_map()
        self._refresh_device_status()
        self._update_speed_mode()
        QTimer.singleShot(0, self._position_overlays)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_overlays)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override name
        if watched is getattr(self, "map_stage", None) and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._position_overlays)
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        self.setStyleSheet(APP_STYLES)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("topBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 18, 0)
        header_layout.setSpacing(10)

        logo = QLabel("G")
        logo.setObjectName("logo")
        logo_png = resource_path("assets/app_icon.png")
        if logo_png.exists():
            logo.setPixmap(QPixmap(str(logo_png)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo.setText("")
        title = QLabel("gps-another")
        title.setObjectName("appTitle")
        subtitle = QLabel("iPhone location simulation MVP")
        subtitle.setObjectName("appSubtitle")
        header_layout.addWidget(logo)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addStretch(1)

        self.device_status_label = QLabel("device: checking")
        self.device_status_label.setObjectName("deviceChip")
        self.device_detail_label = QLabel("")
        self.device_detail_label.setObjectName("deviceDetail")
        refresh_button = QToolButton()
        refresh_button.setText("↻")
        refresh_button.setToolTip("端末状態を更新")
        refresh_button.clicked.connect(self._refresh_device_status)
        header_layout.addWidget(self.device_status_label)
        header_layout.addWidget(refresh_button)

        self.map_stage = QWidget()
        self.map_stage.setObjectName("mapStage")
        self.map_stage.installEventFilter(self)
        self.map_view = QWebEngineView(self.map_stage)

        root_layout.addWidget(header, 0)
        root_layout.addWidget(self.map_stage, 1)
        self.setCentralWidget(root)

        self._build_search_overlay()
        self._build_side_panel()
        self._build_mode_overlay()
        self._build_map_tools()
        self._build_notice_bar()

    def _build_search_overlay(self) -> None:
        self.search_panel = QFrame(self.map_stage)
        self.search_panel.setObjectName("searchPanel")
        layout = QHBoxLayout(self.search_panel)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        self.coordinate_input = QLineEdit()
        self.coordinate_input.setObjectName("coordinateInput")
        self.coordinate_input.setPlaceholderText("緯度,経度を入力 例: 35.6812362,139.7671248")
        self.coordinate_input.returnPressed.connect(self._add_or_replace_point_from_inputs)

        self.add_point_button = QPushButton("＋")
        self.add_point_button.setObjectName("searchButton")
        self.add_point_button.setToolTip("入力座標をポイントに追加または選択行へ置換")
        self.add_point_button.clicked.connect(self._add_or_replace_point_from_inputs)

        layout.addWidget(self.coordinate_input, 1)
        layout.addWidget(self.add_point_button)

    def _build_side_panel(self) -> None:
        self.side_panel = QFrame(self.map_stage)
        self.side_panel.setObjectName("sidePanel")
        layout = QVBoxLayout(self.side_panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.mode_title_label = QLabel("2か所モード")
        self.mode_title_label.setAlignment(Qt.AlignCenter)
        self.mode_title_label.setObjectName("panelTitle")
        layout.addWidget(self.mode_title_label)

        route_header = QHBoxLayout()
        route_label = QLabel("◇ ルート")
        route_label.setObjectName("sectionLabel")
        self.route_button = QPushButton("取得")
        self.route_button.setObjectName("smallPrimary")
        self.route_button.clicked.connect(self._fetch_route)
        clear_button = QPushButton("消去")
        clear_button.setObjectName("smallGhost")
        clear_button.clicked.connect(self._clear_points)
        route_header.addWidget(route_label)
        route_header.addStretch(1)
        route_header.addWidget(clear_button)
        route_header.addWidget(self.route_button)
        layout.addLayout(route_header)

        self.points_table = QTableWidget(0, 3)
        self.points_table.setObjectName("pointsTable")
        self.points_table.setHorizontalHeaderLabels(["#", "地点", "座標"])
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.horizontalHeader().setVisible(False)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.points_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.points_table.itemSelectionChanged.connect(self._sync_inputs_from_selection)
        self.points_table.setFixedHeight(118)
        layout.addWidget(self.points_table)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("divider")
        layout.addWidget(divider)

        speed_row = QHBoxLayout()
        self.speed_value_label = QLabel()
        self.speed_value_label.setObjectName("metricLabel")
        self.mode_label = QLabel()
        self.mode_label.setObjectName("modeBadge")
        speed_row.addWidget(self.speed_value_label)
        speed_row.addStretch(1)
        speed_row.addWidget(self.mode_label)
        layout.addLayout(speed_row)

        mode_icons = QHBoxLayout()
        for text, tooltip in [("歩", "徒歩ルート"), ("自", "自転車ルート"), ("車", "車ルート（高速道路を回避）")]:
            chip = QLabel(text)
            chip.setObjectName("modeIcon")
            chip.setToolTip(tooltip)
            chip.setAlignment(Qt.AlignCenter)
            mode_icons.addWidget(chip)
        layout.addLayout(mode_icons)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(CONFIG.min_speed_kmh, CONFIG.max_speed_kmh)
        self.speed_slider.setValue(CONFIG.default_speed_kmh)
        self.speed_slider.valueChanged.connect(self._update_speed_mode)

        speed_input_row = QHBoxLayout()
        speed_input_label = QLabel("速度")
        speed_input_label.setObjectName("subtleLabel")
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(CONFIG.min_speed_kmh, CONFIG.max_speed_kmh)
        self.speed_spin.setSuffix(" km/h")
        self.speed_spin.setValue(CONFIG.default_speed_kmh)
        self.speed_spin.setObjectName("speedSpin")
        self.speed_spin.valueChanged.connect(self.speed_slider.setValue)
        self.speed_slider.valueChanged.connect(self.speed_spin.setValue)
        speed_input_row.addWidget(speed_input_label)
        speed_input_row.addStretch(1)
        speed_input_row.addWidget(self.speed_spin)
        layout.addLayout(speed_input_row)
        layout.addWidget(self.speed_slider)

        self.trip_label = QLabel("移動 1 回")
        self.trip_label.setObjectName("subtleLabel")
        layout.addWidget(self.trip_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        summary_grid = QGridLayout()
        self.distance_label = QLabel("距離: -- KM")
        self.duration_label = QLabel("--:--:--")
        self.distance_label.setObjectName("summaryLabel")
        self.duration_label.setObjectName("summaryLabel")
        summary_grid.addWidget(QLabel("◇"), 0, 0)
        summary_grid.addWidget(self.distance_label, 0, 1)
        summary_grid.addWidget(self.duration_label, 0, 2, Qt.AlignRight)
        layout.addLayout(summary_grid)

        controls = QGridLayout()
        self.start_button = QPushButton("開始")
        self.pause_button = QPushButton("一時停止")
        self.resume_button = QPushButton("続ける")
        self.stop_button = QPushButton("停止")
        self.start_button.setObjectName("primaryButton")
        self.resume_button.setObjectName("primaryButton")
        self.pause_button.setObjectName("ghostButton")
        self.stop_button.setObjectName("dangerButton")
        self.start_button.clicked.connect(self._start_playback)
        self.pause_button.clicked.connect(self._pause_playback)
        self.resume_button.clicked.connect(self._resume_playback)
        self.stop_button.clicked.connect(self._stop_playback)
        controls.addWidget(self.start_button, 0, 0)
        controls.addWidget(self.pause_button, 0, 1)
        controls.addWidget(self.stop_button, 1, 0)
        controls.addWidget(self.resume_button, 1, 1)
        layout.addLayout(controls)

        self.status_text = QLabel("地図をクリックして最大 4 点まで指定できます。")
        self.status_text.setObjectName("statusText")
        self.status_text.setWordWrap(True)
        layout.addWidget(self.status_text)
        layout.addWidget(self.device_detail_label)

    def _build_mode_overlay(self) -> None:
        self.mode_panel = QFrame(self.map_stage)
        self.mode_panel.setObjectName("modePanel")
        layout = QHBoxLayout(self.mode_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for index, (text, tip) in enumerate([("◎", "現在地モード"), ("⌁", "ルートモード"), ("⌘", "複数ポイント")]):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setObjectName("modeTabActive" if index == 1 else "modeTab")
            layout.addWidget(button)

    def _build_map_tools(self) -> None:
        self.map_tools = QFrame(self.map_stage)
        self.map_tools.setObjectName("mapTools")
        layout = QVBoxLayout(self.map_tools)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for text, tip in [("⌂", "全体表示"), ("☆", "保存候補"), ("↶", "戻る"), ("⊙", "現在位置"), ("＋", "ズームイン"), ("－", "ズームアウト")]:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setObjectName("mapToolButton")
            layout.addWidget(button)

    def _build_notice_bar(self) -> None:
        self.notice_bar = QFrame(self.map_stage)
        self.notice_bar.setObjectName("noticeBar")
        layout = QHBoxLayout(self.notice_bar)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)
        icon = QLabel("!")
        icon.setObjectName("noticeIcon")
        label = QLabel("動作中は、デバイスの接続を解除したりデベロッパモードをオフにしないでください。")
        label.setObjectName("noticeText")
        close = QToolButton()
        close.setText("×")
        close.setObjectName("noticeClose")
        close.clicked.connect(self.notice_bar.hide)
        layout.addWidget(icon)
        layout.addWidget(label, 1)
        layout.addWidget(close)

    def _position_overlays(self) -> None:
        rect = self.map_stage.rect()
        self.map_view.setGeometry(rect)

        margin = 16
        search_width = min(480, max(360, rect.width() - 560))
        self.search_panel.setGeometry(margin, 16, search_width, 46)
        panel_height = min(540, max(500, rect.height() - 104))
        self.side_panel.setGeometry(margin, 78, 322, panel_height)
        self.mode_panel.setGeometry(rect.width() - 202, 16, 170, 40)
        self.map_tools.setGeometry(rect.width() - 50, max(96, rect.height() // 2 - 105), 38, 210)
        notice_width = min(520, rect.width() - 360)
        self.notice_bar.setGeometry(rect.width() - notice_width - 24, rect.height() - 42, notice_width, 32)

        for widget in [self.search_panel, self.side_panel, self.mode_panel, self.map_tools, self.notice_bar]:
            widget.raise_()

    def _load_map(self) -> None:
        channel = QWebChannel(self.map_view.page())
        channel.registerObject("bridge", self.bridge)
        self.map_view.page().setWebChannel(channel)
        self.map_view.setHtml(MAP_HTML)

    def _refresh_device_status(self) -> None:
        status = self.device_manager.check_status()
        self._render_device_status(status)

    def _render_device_status(self, status: DeviceStatus) -> None:
        state = "接続済み" if status.detected else "未検出"
        pair = "ペアリング済み" if status.paired else "ペアリング未確認"
        self.device_status_label.setText(f"{state} / {pair}")
        self.device_detail_label.setText(status.detail)

    @Slot(float, float)
    def _add_point_from_map(self, latitude: float, longitude: float) -> None:
        if len(self.points) >= CONFIG.max_points:
            self._set_status("ポイントは最大 4 点までです。不要な点を消去してください。")
            return
        self.points.append((latitude, longitude))
        self.coordinate_input.setText(f"{latitude:.7f},{longitude:.7f}")
        self._points_changed()

    def _add_or_replace_point_from_inputs(self) -> None:
        parsed = self._parse_coordinate_input()
        if parsed is None:
            self._set_status("緯度,経度 の形式で入力してください。例: 35.6812362,139.7671248")
            return

        selected_row = self.points_table.currentRow()
        if 0 <= selected_row < len(self.points):
            self.points[selected_row] = parsed
        elif len(self.points) < CONFIG.max_points:
            self.points.append(parsed)
        else:
            self._set_status("ポイントは最大 4 点までです。既存行を選択して置換してください。")
            return
        self._points_changed()

    def _parse_coordinate_input(self) -> Coordinate | None:
        raw = self.coordinate_input.text().strip().replace("，", ",")
        if not raw:
            return None
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 2:
            return None
        try:
            latitude = float(parts[0])
            longitude = float(parts[1])
        except ValueError:
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        return latitude, longitude

    def _clear_points(self) -> None:
        self.send_timer.stop()
        self.points.clear()
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self.current_send_index = 0
        self._points_changed()
        self._run_js("setRoute([]); clearCurrent();")
        self._render_route_summary()
        self.progress_bar.setValue(0)
        self._set_status("ポイントとルートをクリアしました。")

    def _points_changed(self) -> None:
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self.current_send_index = 0
        self._render_points_table()
        self._render_route_summary()
        self._run_js(f"setPoints({json.dumps(self._js_points(self.points))}); setRoute([]); clearCurrent();")

    def _render_points_table(self) -> None:
        self.mode_title_label.setText(f"{max(2, len(self.points))}か所モード")
        self.points_table.setRowCount(len(self.points))
        for row, (lat, lon) in enumerate(self.points):
            self.points_table.setItem(row, 0, QTableWidgetItem(f"{row + 1}"))
            self.points_table.setItem(row, 1, QTableWidgetItem("指定地点"))
            self.points_table.setItem(row, 2, QTableWidgetItem(f"{lat:.7f},{lon:.7f}"))
        self.points_table.setColumnWidth(0, 28)
        self.points_table.setColumnWidth(1, 76)
        self.points_table.setColumnWidth(2, 190)

    def _sync_inputs_from_selection(self) -> None:
        row = self.points_table.currentRow()
        if 0 <= row < len(self.points):
            lat, lon = self.points[row]
            self.coordinate_input.setText(f"{lat:.7f},{lon:.7f}")

    def _update_speed_mode(self) -> None:
        speed = self.speed_slider.value()
        mode = mode_for_speed(speed)
        meters_per_second = speed * 1000 / 3600
        self.speed_value_label.setText(f"スピード: {meters_per_second:.1f}m/s  {speed}km/h")
        self.mode_label.setText(mode.value)

        if self.route_coordinates and self.route_mode is mode:
            self.transmission_plan = build_transmission_plan(
                self.route_coordinates,
                speed,
                CONFIG.send_interval_seconds,
            )
            self._render_route_summary()
        elif self.route_coordinates and self.route_mode is not mode:
            self.route_coordinates.clear()
            self.route_mode = None
            self.transmission_plan = None
            self.progress_bar.setValue(0)
            self._run_js("setRoute([]); clearCurrent();")
            self._render_route_summary()
            self._set_status("速度帯が変わったためルートを再取得してください。")

    def _fetch_route(self) -> None:
        if len(self.points) < 2:
            self._set_status("ルート取得には少なくとも 2 点が必要です。")
            return
        if self.send_timer.isActive():
            self._set_status("送信中はルートを変更できません。停止後に再取得してください。")
            return

        self.route_button.setEnabled(False)
        speed = self.speed_slider.value()
        self._set_status("ルートを取得中です。")
        self.route_thread = RouteFetchThread(self.points, speed)
        self.route_thread.succeeded.connect(self._route_fetch_succeeded)
        self.route_thread.failed.connect(self._route_fetch_failed)
        self.route_thread.finished.connect(lambda: self.route_button.setEnabled(True))
        self.route_thread.finished.connect(self.route_thread.deleteLater)
        self.route_thread.start()

    @Slot(object)
    def _route_fetch_succeeded(self, result: RouteResult) -> None:
        self.route_coordinates = result.coordinates
        self.route_mode = result.mode
        self.transmission_plan = build_transmission_plan(
            self.route_coordinates,
            self.speed_slider.value(),
            CONFIG.send_interval_seconds,
        )
        self.current_send_index = 0
        self.progress_bar.setValue(0)
        self._run_js(f"setRoute({json.dumps(self._js_points(self.route_coordinates))}); clearCurrent();")
        self._render_route_summary(result)
        self._set_status(f"{result.provider} から {len(result.coordinates)} 点のルートを取得しました。")

    @Slot(str)
    def _route_fetch_failed(self, message: str) -> None:
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self.progress_bar.setValue(0)
        self._run_js("setRoute([]); clearCurrent();")
        self._render_route_summary()
        self._set_status(
            "ルート取得に失敗しました。端末接続状態、Developer Mode、APIキー、指定地点を確認してください。\n"
            f"詳細: {message}"
        )

    def _render_route_summary(self, result: RouteResult | None = None) -> None:
        if not self.transmission_plan:
            self.distance_label.setText("距離: -- KM")
            self.duration_label.setText("--:--:--")
            return

        speed_mps = self.speed_slider.value() * 1000 / 3600
        distance_km = self.transmission_plan.total_distance_meters / 1000
        seconds = self.transmission_plan.total_distance_meters / speed_mps if speed_mps else 0
        self.distance_label.setText(f"距離: {distance_km:.2f} KM")
        self.duration_label.setText(_format_duration(seconds))

    def _start_playback(self) -> None:
        if not self.transmission_plan or not self.transmission_plan.points:
            self._set_status("送信開始前にルートを取得してください。")
            return
        self.current_send_index = 0
        self.progress_bar.setValue(0)
        interval_ms = int(self.transmission_plan.interval_seconds * 1000)
        self.send_timer.start(interval_ms)
        self._set_status("送信を開始しました。MVP ではモック送信として画面とコンソールへ座標を出力します。")

    def _pause_playback(self) -> None:
        if self.send_timer.isActive():
            self.send_timer.stop()
            self._set_status("送信を一時停止しました。")

    def _resume_playback(self) -> None:
        if not self.transmission_plan or self.current_send_index >= len(self.transmission_plan.points):
            self._set_status("再開できる送信計画がありません。")
            return
        if not self.send_timer.isActive():
            interval_ms = int(self.transmission_plan.interval_seconds * 1000)
            self.send_timer.start(interval_ms)
            self._set_status("送信を再開しました。")

    def _stop_playback(self) -> None:
        self.send_timer.stop()
        self.current_send_index = 0
        self.progress_bar.setValue(0)
        self.location_sender.clear()
        self._run_js("clearCurrent();")
        self._set_status("送信を停止し、疑似位置情報の解除処理を呼び出しました。")

    def _send_next_location(self) -> None:
        if not self.transmission_plan:
            self.send_timer.stop()
            return
        if self.current_send_index >= len(self.transmission_plan.points):
            self._stop_playback()
            self._set_status("送信計画の最後まで到達しました。")
            return

        point = self.transmission_plan.points[self.current_send_index]
        self.location_sender.send(point.latitude, point.longitude)
        self._run_js(f"setCurrent({point.latitude:.10f}, {point.longitude:.10f});")
        total = len(self.transmission_plan.points)
        progress = int(((self.current_send_index + 1) / total) * 100)
        self.progress_bar.setValue(progress)
        self._set_status(f"送信予定: {point.latitude:.7f}, {point.longitude:.7f}")
        self.current_send_index += 1

    def _set_status(self, message: str) -> None:
        self.status_text.setText(message)

    def _run_js(self, script: str) -> None:
        self.map_view.page().runJavaScript(script)

    @staticmethod
    def _js_points(points: Sequence[Coordinate]) -> list[dict[str, float]]:
        return [{"lat": lat, "lng": lon} for lat, lon in points]


def _format_duration(seconds: float) -> str:
    rounded = int(seconds)
    hours = rounded // 3600
    minutes = (rounded % 3600) // 60
    secs = rounded % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


APP_STYLES = """
QMainWindow {
    background: #f5f7fb;
    font-family: "Segoe UI", "Meiryo";
    color: #18213a;
}
#topBar {
    background: #ffffff;
    border-bottom: 1px solid #e6e8f0;
    min-height: 46px;
    max-height: 46px;
}
#logo {
    background: #050505;
    color: white;
    border-radius: 5px;
    min-width: 28px;
    min-height: 28px;
    max-width: 28px;
    max-height: 28px;
    font-weight: 800;
    qproperty-alignment: AlignCenter;
}
#appTitle {
    font-size: 16px;
    font-weight: 700;
}
#appSubtitle {
    color: #7a859f;
    font-size: 12px;
}
#deviceChip {
    color: #5365d9;
    background: #eef1ff;
    border: 1px solid #dde3ff;
    border-radius: 12px;
    padding: 4px 10px;
}
#mapStage {
    background: #dce7f7;
}
#searchPanel, #sidePanel, #modePanel, #mapTools, #noticeBar {
    background: rgba(255, 255, 255, 238);
    border: 1px solid rgba(218, 224, 241, 210);
    border-radius: 7px;
}
#coordinateInput {
    border: 0;
    background: transparent;
    color: #5d6f9c;
    font-size: 13px;
    padding: 4px;
}
#searchButton {
    background: #aeb8ff;
    color: #ffffff;
    border: 0;
    border-radius: 5px;
    font-size: 19px;
    min-width: 38px;
    min-height: 30px;
}
#sidePanel {
    background: rgba(249, 251, 255, 242);
}
#panelTitle {
    font-size: 16px;
    font-weight: 700;
    color: #16234a;
}
#sectionLabel {
    color: #6778d8;
    font-weight: 600;
}
#smallPrimary, #primaryButton {
    background: #6072ff;
    color: #ffffff;
    border: 0;
    border-radius: 5px;
    padding: 7px 14px;
    font-weight: 700;
}
#smallGhost, #ghostButton, #dangerButton {
    background: #ffffff;
    color: #6072ff;
    border: 1px solid #6072ff;
    border-radius: 5px;
    padding: 7px 12px;
    font-weight: 700;
}
#dangerButton {
    color: #5365ff;
    border-color: #5365ff;
}
#pointsTable {
    background: #ffffff;
    border: 0;
    gridline-color: #eef1f7;
    color: #223154;
}
#pointsTable::item {
    padding: 4px;
}
#divider {
    color: #e7ebf5;
}
#metricLabel {
    color: #5667a8;
    font-weight: 700;
}
#modeBadge {
    color: #ffffff;
    background: #6175ff;
    border-radius: 10px;
    padding: 3px 9px;
}
#modeIcon {
    color: #6276ff;
    min-height: 20px;
    font-weight: 800;
}
#speedSpin {
    color: #233360;
    background: #ffffff;
    border: 1px solid #dbe2f5;
    border-radius: 5px;
    padding: 4px 8px;
    min-width: 88px;
}
QSlider::groove:horizontal {
    height: 2px;
    background: #aeb8ea;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #8390e6;
    width: 10px;
    height: 10px;
    margin: -6px 0;
    border-radius: 7px;
}
QProgressBar {
    border: 0;
    background: #e7ecf4;
    height: 3px;
}
QProgressBar::chunk {
    background: #ffad2f;
}
#subtleLabel, #deviceDetail, #statusText {
    color: #6c7895;
    font-size: 12px;
}
#summaryLabel {
    color: #233360;
    font-size: 14px;
    font-weight: 700;
}
#modeTab, #modeTabActive, #mapToolButton {
    background: #ffffff;
    border: 0;
    color: #9da9d4;
    font-size: 18px;
    min-width: 38px;
    min-height: 38px;
}
#modeTabActive {
    background: #6072ff;
    color: #ffffff;
}
#mapToolButton {
    border: 1px solid #dbe2f1;
    border-radius: 5px;
    color: #6b7dd9;
    min-width: 36px;
    min-height: 30px;
}
#noticeBar {
    background: rgba(255, 249, 229, 245);
    border: 1px solid #ffe0a8;
}
#noticeIcon {
    background: #ff982f;
    color: #ffffff;
    border-radius: 8px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 11px;
    font-weight: 800;
    qproperty-alignment: AlignCenter;
}
#noticeText {
    color: #4f5b74;
    font-size: 12px;
}
#noticeClose {
    border: 0;
    background: transparent;
    color: #77819c;
}
"""


MAP_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <style>
    html, body, #map {
      height: 100%;
      margin: 0;
      font-family: Arial, sans-serif;
      background: #d8e6f6;
    }
    .leaflet-control-zoom {
      display: none;
    }
    .point-label {
      background: #6175ff;
      border: 2px solid #ffffff;
      border-radius: 50%;
      box-shadow: 0 4px 12px rgba(69, 87, 213, 0.35);
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      height: 22px;
      line-height: 18px;
      text-align: center;
      width: 22px;
    }
    .current-pulse {
      background: rgba(96, 114, 255, 0.22);
      border: 0;
      border-radius: 50%;
      height: 46px;
      position: relative;
      width: 46px;
    }
    .current-pulse::after {
      background: #6072ff;
      border: 4px solid #ffffff;
      border-radius: 50%;
      box-shadow: 0 6px 18px rgba(71, 85, 204, 0.45);
      content: "";
      height: 14px;
      left: 12px;
      position: absolute;
      top: 12px;
      width: 14px;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const map = L.map('map', { zoomControl: true }).setView([35.6812362, 139.7671248], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    let bridge = null;
    let pointLayer = L.layerGroup().addTo(map);
    let routeLayer = L.layerGroup().addTo(map);
    let currentMarker = null;

    new QWebChannel(qt.webChannelTransport, function(channel) {
      bridge = channel.objects.bridge;
    });

    map.on('click', function(event) {
      if (bridge) {
        bridge.handleMapClick(event.latlng.lat, event.latlng.lng);
      }
    });

    function setPoints(points) {
      pointLayer.clearLayers();
      points.forEach(function(point, index) {
        const marker = L.marker([point.lat, point.lng], {
          icon: L.divIcon({
            html: String(index + 1),
            className: 'point-label',
            iconSize: [22, 22],
            iconAnchor: [11, 11]
          })
        }).addTo(pointLayer);
        marker.bindPopup((index + 1) + ': ' + point.lat.toFixed(7) + ', ' + point.lng.toFixed(7));
      });
      fitVisible(points);
    }

    function setRoute(points) {
      routeLayer.clearLayers();
      if (!points || points.length === 0) {
        return;
      }
      const latlngs = points.map(function(point) { return [point.lat, point.lng]; });
      L.polyline(latlngs, { color: '#ffffff', weight: 8, opacity: 0.75 }).addTo(routeLayer);
      L.polyline(latlngs, { color: '#ffad2f', weight: 4, opacity: 0.98 }).addTo(routeLayer);
      fitVisible(points);
    }

    function setCurrent(lat, lng) {
      const icon = L.divIcon({
        html: '<div class="current-pulse"></div>',
        className: '',
        iconSize: [46, 46],
        iconAnchor: [23, 23]
      });
      if (currentMarker) {
        currentMarker.setLatLng([lat, lng]);
      } else {
        currentMarker = L.marker([lat, lng], { icon: icon, zIndexOffset: 1000 }).addTo(map);
      }
    }

    function clearCurrent() {
      if (currentMarker) {
        currentMarker.remove();
        currentMarker = null;
      }
    }

    function fitVisible(points) {
      if (!points || points.length === 0) {
        return;
      }
      const bounds = L.latLngBounds(points.map(function(point) { return [point.lat, point.lng]; }));
      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.25), { maxZoom: 16 });
      }
    }
  </script>
</body>
</html>
"""
