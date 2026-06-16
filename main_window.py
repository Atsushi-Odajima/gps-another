from __future__ import annotations

import json
from typing import Sequence

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import CONFIG
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
        except Exception as exc:  # Defensive boundary for GUI thread safety.
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

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        controls = QWidget()
        controls.setFixedWidth(380)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        controls_layout.addWidget(self._build_device_group())
        controls_layout.addWidget(self._build_points_group())
        controls_layout.addWidget(self._build_speed_group())
        controls_layout.addWidget(self._build_route_group())
        controls_layout.addStretch(1)

        self.map_view = QWebEngineView()

        root_layout.addWidget(controls)
        root_layout.addWidget(self.map_view, 1)
        self.setCentralWidget(root)

    def _build_device_group(self) -> QGroupBox:
        group = QGroupBox("Device")
        layout = QGridLayout(group)

        self.device_status_label = QLabel("-")
        self.device_detail_label = QLabel("-")
        self.device_detail_label.setWordWrap(True)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_device_status)

        layout.addWidget(QLabel("Status"), 0, 0)
        layout.addWidget(self.device_status_label, 0, 1)
        layout.addWidget(QLabel("Detail"), 1, 0, Qt.AlignTop)
        layout.addWidget(self.device_detail_label, 1, 1)
        layout.addWidget(refresh_button, 2, 1)
        return group

    def _build_points_group(self) -> QGroupBox:
        group = QGroupBox("Points")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90.0, 90.0)
        self.lat_input.setDecimals(7)
        self.lat_input.setSingleStep(0.0001)
        self.lat_input.setValue(35.6812362)

        self.lon_input = QDoubleSpinBox()
        self.lon_input.setRange(-180.0, 180.0)
        self.lon_input.setDecimals(7)
        self.lon_input.setSingleStep(0.0001)
        self.lon_input.setValue(139.7671248)

        form.addRow("Latitude", self.lat_input)
        form.addRow("Longitude", self.lon_input)
        layout.addLayout(form)

        input_buttons = QHBoxLayout()
        self.add_point_button = QPushButton("Add / Replace")
        self.add_point_button.clicked.connect(self._add_or_replace_point_from_inputs)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_points)
        input_buttons.addWidget(self.add_point_button)
        input_buttons.addWidget(clear_button)
        layout.addLayout(input_buttons)

        self.points_table = QTableWidget(0, 3)
        self.points_table.setHorizontalHeaderLabels(["#", "Latitude", "Longitude"])
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.points_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.points_table.itemSelectionChanged.connect(self._sync_inputs_from_selection)
        layout.addWidget(self.points_table)
        return group

    def _build_speed_group(self) -> QGroupBox:
        group = QGroupBox("Speed")
        layout = QVBoxLayout(group)

        self.speed_value_label = QLabel()
        self.mode_label = QLabel()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(CONFIG.min_speed_kmh, CONFIG.max_speed_kmh)
        self.speed_slider.setValue(CONFIG.default_speed_kmh)
        self.speed_slider.valueChanged.connect(self._update_speed_mode)

        layout.addWidget(self.speed_value_label)
        layout.addWidget(self.speed_slider)
        layout.addWidget(self.mode_label)
        return group

    def _build_route_group(self) -> QGroupBox:
        group = QGroupBox("Route / Playback")
        layout = QVBoxLayout(group)

        self.route_button = QPushButton("Fetch Route")
        self.route_button.clicked.connect(self._fetch_route)
        layout.addWidget(self.route_button)

        playback = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.start_button.clicked.connect(self._start_playback)
        self.pause_button.clicked.connect(self._pause_playback)
        self.resume_button.clicked.connect(self._resume_playback)
        self.stop_button.clicked.connect(self._stop_playback)
        playback.addWidget(self.start_button)
        playback.addWidget(self.pause_button)
        playback.addWidget(self.resume_button)
        playback.addWidget(self.stop_button)
        layout.addLayout(playback)

        self.route_summary_label = QLabel("Route: -")
        self.route_summary_label.setWordWrap(True)
        layout.addWidget(self.route_summary_label)

        self.status_text = QPlainTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumBlockCount(120)
        self.status_text.setFixedHeight(160)
        layout.addWidget(self.status_text)
        return group

    def _load_map(self) -> None:
        channel = QWebChannel(self.map_view.page())
        channel.registerObject("bridge", self.bridge)
        self.map_view.page().setWebChannel(channel)
        self.map_view.setHtml(MAP_HTML)

    def _refresh_device_status(self) -> None:
        status = self.device_manager.check_status()
        self._render_device_status(status)

    def _render_device_status(self, status: DeviceStatus) -> None:
        state = "Detected" if status.detected else "Not detected"
        pair = "paired" if status.paired else "pairing unknown"
        dev = "Developer Mode assumed enabled" if status.developer_mode_assumed else "Developer Mode unknown"
        self.device_status_label.setText(f"{state} / {pair}")
        self.device_detail_label.setText(f"{dev}\n{status.detail}")

    @Slot(float, float)
    def _add_point_from_map(self, latitude: float, longitude: float) -> None:
        if len(self.points) >= CONFIG.max_points:
            self._set_status("ポイントは最大 4 点までです。不要な点を Clear してください。")
            return
        self.points.append((latitude, longitude))
        self._points_changed()

    def _add_or_replace_point_from_inputs(self) -> None:
        point = (self.lat_input.value(), self.lon_input.value())
        selected_row = self.points_table.currentRow()
        if 0 <= selected_row < len(self.points):
            self.points[selected_row] = point
        elif len(self.points) < CONFIG.max_points:
            self.points.append(point)
        else:
            self._set_status("ポイントは最大 4 点までです。既存行を選択して置換してください。")
            return
        self._points_changed()

    def _clear_points(self) -> None:
        self.points.clear()
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self.current_send_index = 0
        self._points_changed()
        self._run_js("setRoute([]); clearCurrent();")
        self.route_summary_label.setText("Route: -")
        self._set_status("ポイントとルートをクリアしました。")

    def _points_changed(self) -> None:
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self.current_send_index = 0
        self._render_points_table()
        self._run_js(f"setPoints({json.dumps(self._js_points(self.points))}); setRoute([]); clearCurrent();")

    def _render_points_table(self) -> None:
        self.points_table.setRowCount(len(self.points))
        for row, (lat, lon) in enumerate(self.points):
            self.points_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.points_table.setItem(row, 1, QTableWidgetItem(f"{lat:.7f}"))
            self.points_table.setItem(row, 2, QTableWidgetItem(f"{lon:.7f}"))
        self.points_table.resizeColumnsToContents()

    def _sync_inputs_from_selection(self) -> None:
        row = self.points_table.currentRow()
        if 0 <= row < len(self.points):
            lat, lon = self.points[row]
            self.lat_input.setValue(lat)
            self.lon_input.setValue(lon)

    def _update_speed_mode(self) -> None:
        speed = self.speed_slider.value()
        mode = mode_for_speed(speed)
        self.speed_value_label.setText(f"{speed} km/h")
        self.mode_label.setText(f"Mode: {mode.value}")

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
            self._run_js("setRoute([]); clearCurrent();")
            self.route_summary_label.setText("Route: speed mode changed. Fetch route again.")
            self._set_status("速度帯が変わったためルートを再取得してください。")

    def _fetch_route(self) -> None:
        if len(self.points) < 2:
            self._set_status("ルート取得には少なくとも 2 点が必要です。")
            return
        if self.send_timer.isActive():
            self._set_status("送信中はルートを変更できません。Stop 後に再取得してください。")
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
        self._run_js(f"setRoute({json.dumps(self._js_points(self.route_coordinates))}); clearCurrent();")
        self._render_route_summary(result)
        self._set_status(f"{result.provider} から {len(result.coordinates)} 点のルートを取得しました。")

    @Slot(str)
    def _route_fetch_failed(self, message: str) -> None:
        self.route_coordinates.clear()
        self.route_mode = None
        self.transmission_plan = None
        self._run_js("setRoute([]); clearCurrent();")
        self.route_summary_label.setText("Route: failed")
        self._set_status(
            "ルート取得に失敗しました。\n"
            "確認項目: APIキー、ネットワーク、指定ポイント、速度帯に対応するルート種別。\n"
            f"詳細: {message}"
        )

    def _render_route_summary(self, result: RouteResult | None = None) -> None:
        if not self.transmission_plan:
            self.route_summary_label.setText("Route: -")
            return

        provider = result.provider if result else "current route"
        mode = result.mode.value if result else (self.route_mode.value if self.route_mode else "-")
        distance_km = self.transmission_plan.total_distance_meters / 1000
        send_count = len(self.transmission_plan.points)
        self.route_summary_label.setText(
            f"Route: {provider} / {mode} / {distance_km:.2f} km / {send_count} sends"
        )

    def _start_playback(self) -> None:
        if not self.transmission_plan or not self.transmission_plan.points:
            self._set_status("送信開始前にルートを取得してください。")
            return
        self.current_send_index = 0
        interval_ms = int(self.transmission_plan.interval_seconds * 1000)
        self.send_timer.start(interval_ms)
        self._set_status("送信を開始しました。MVP ではコンソールに座標を出力します。")

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
        self.current_send_index += 1

    def _set_status(self, message: str) -> None:
        self.status_text.appendPlainText(message)

    def _run_js(self, script: str) -> None:
        self.map_view.page().runJavaScript(script)

    @staticmethod
    def _js_points(points: Sequence[Coordinate]) -> list[dict[str, float]]:
        return [{"lat": lat, "lng": lon} for lat, lon in points]


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
    }
    .point-label {
      background: #1e293b;
      border: 0;
      border-radius: 50%;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      height: 22px;
      line-height: 22px;
      text-align: center;
      width: 22px;
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
        const marker = L.marker([point.lat, point.lng]).addTo(pointLayer);
        marker.bindTooltip(String(index + 1), {
          permanent: true,
          direction: 'center',
          className: 'point-label',
          opacity: 1
        });
      });
      fitVisible(points);
    }

    function setRoute(points) {
      routeLayer.clearLayers();
      if (!points || points.length === 0) {
        return;
      }
      const latlngs = points.map(function(point) { return [point.lat, point.lng]; });
      L.polyline(latlngs, { color: '#2563eb', weight: 5, opacity: 0.86 }).addTo(routeLayer);
      fitVisible(points);
    }

    function setCurrent(lat, lng) {
      if (currentMarker) {
        currentMarker.setLatLng([lat, lng]);
      } else {
        currentMarker = L.circleMarker([lat, lng], {
          radius: 8,
          color: '#111827',
          fillColor: '#f97316',
          fillOpacity: 1,
          weight: 3
        }).addTo(map);
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

