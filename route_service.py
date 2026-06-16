from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

import requests

from config import AppConfig
from route_interpolator import Coordinate, normalize_coordinates


class RouteMode(Enum):
    WALK = "徒歩"
    BICYCLE = "自転車"
    CAR = "車"


@dataclass(frozen=True)
class RouteResult:
    coordinates: list[Coordinate]
    provider: str
    mode: RouteMode
    distance_meters: float | None = None
    duration_seconds: float | None = None


class RouteServiceError(RuntimeError):
    pass


def mode_for_speed(speed_kmh: float) -> RouteMode:
    if 1 <= speed_kmh <= 6:
        return RouteMode.WALK
    if 7 <= speed_kmh <= 29:
        return RouteMode.BICYCLE
    if 30 <= speed_kmh <= 40:
        return RouteMode.CAR
    raise ValueError("速度は 1km/h から 40km/h の範囲で指定してください")


class RouteService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def fetch_route(self, points: Sequence[Coordinate], speed_kmh: float) -> RouteResult:
        normalized = normalize_coordinates(points)
        if len(normalized) < 2:
            raise RouteServiceError("ルート取得には少なくとも 2 点が必要です")

        mode = mode_for_speed(speed_kmh)
        errors: list[str] = []

        if self.config.ors_api_key:
            try:
                return self._fetch_openrouteservice(normalized, mode)
            except RouteServiceError as exc:
                errors.append(f"OpenRouteService: {exc}")
        else:
            errors.append("OpenRouteService: ORS_API_KEY が未設定です")

        if self.config.graphhopper_api_key:
            try:
                return self._fetch_graphhopper(normalized, mode)
            except RouteServiceError as exc:
                errors.append(f"GraphHopper: {exc}")
        else:
            errors.append("GraphHopper: GRAPHHOPPER_API_KEY が未設定です")

        if mode is not RouteMode.CAR:
            try:
                return self._fetch_osrm(normalized, mode)
            except RouteServiceError as exc:
                errors.append(f"OSRM: {exc}")
        else:
            errors.append("OSRM: 車ルートの高速道路回避を保証できないため使用しません")

        raise RouteServiceError(" / ".join(errors))

    def _fetch_openrouteservice(
        self,
        points: Sequence[Coordinate],
        mode: RouteMode,
    ) -> RouteResult:
        profile = {
            RouteMode.WALK: "foot-walking",
            RouteMode.BICYCLE: "cycling-regular",
            RouteMode.CAR: "driving-car",
        }[mode]
        url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"
        payload: dict[str, Any] = {
            "coordinates": [[lon, lat] for lat, lon in points],
            "instructions": False,
        }
        if mode is RouteMode.CAR:
            payload["options"] = {"avoid_features": ["highways"]}

        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": self.config.ors_api_key,
                "Content-Type": "application/json",
            },
            timeout=self.config.route_timeout_seconds,
        )
        if not response.ok:
            raise RouteServiceError(_response_error(response))

        data = response.json()
        features = data.get("features") or []
        if not features:
            raise RouteServiceError("ルート候補が返されませんでした")

        geometry = features[0].get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if not coordinates:
            raise RouteServiceError("ルート座標が返されませんでした")

        summary = (features[0].get("properties") or {}).get("summary") or {}
        return RouteResult(
            coordinates=[(lat, lon) for lon, lat in coordinates],
            provider="OpenRouteService",
            mode=mode,
            distance_meters=summary.get("distance"),
            duration_seconds=summary.get("duration"),
        )

    def _fetch_graphhopper(
        self,
        points: Sequence[Coordinate],
        mode: RouteMode,
    ) -> RouteResult:
        vehicle = {
            RouteMode.WALK: "foot",
            RouteMode.BICYCLE: "bike",
            RouteMode.CAR: "car",
        }[mode]
        params: list[tuple[str, str]] = [
            ("vehicle", vehicle),
            ("locale", "ja"),
            ("calc_points", "true"),
            ("points_encoded", "false"),
            ("key", self.config.graphhopper_api_key),
        ]
        for lat, lon in points:
            params.append(("point", f"{lat},{lon}"))
        if mode is RouteMode.CAR:
            params.append(("avoid", "motorway"))

        response = requests.get(
            "https://graphhopper.com/api/1/route",
            params=params,
            timeout=self.config.route_timeout_seconds,
        )
        if not response.ok:
            raise RouteServiceError(_response_error(response))

        data = response.json()
        paths = data.get("paths") or []
        if not paths:
            raise RouteServiceError("ルート候補が返されませんでした")
        path = paths[0]
        coordinates = ((path.get("points") or {}).get("coordinates")) or []
        if not coordinates:
            raise RouteServiceError("ルート座標が返されませんでした")

        return RouteResult(
            coordinates=[(lat, lon) for lon, lat in coordinates],
            provider="GraphHopper",
            mode=mode,
            distance_meters=path.get("distance"),
            duration_seconds=(path.get("time") / 1000.0 if path.get("time") else None),
        )

    def _fetch_osrm(self, points: Sequence[Coordinate], mode: RouteMode) -> RouteResult:
        profile = {
            RouteMode.WALK: "foot",
            RouteMode.BICYCLE: "bike",
            RouteMode.CAR: "car",
        }[mode]
        coordinate_text = ";".join(f"{lon},{lat}" for lat, lon in points)
        url = f"https://router.project-osrm.org/route/v1/{profile}/{coordinate_text}"
        response = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson"},
            timeout=self.config.route_timeout_seconds,
        )
        if not response.ok:
            raise RouteServiceError(_response_error(response))

        data = response.json()
        routes = data.get("routes") or []
        if not routes:
            raise RouteServiceError("ルート候補が返されませんでした")
        route = routes[0]
        coordinates = ((route.get("geometry") or {}).get("coordinates")) or []
        if not coordinates:
            raise RouteServiceError("ルート座標が返されませんでした")

        return RouteResult(
            coordinates=[(lat, lon) for lon, lat in coordinates],
            provider="OSRM",
            mode=mode,
            distance_meters=route.get("distance"),
            duration_seconds=route.get("duration"),
        )


def _response_error(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"
    message = data.get("error") or data.get("message") or data
    return f"HTTP {response.status_code}: {message}"

