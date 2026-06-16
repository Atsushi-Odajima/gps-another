from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Iterable, Sequence


Coordinate = tuple[float, float]


@dataclass(frozen=True)
class TimedCoordinate:
    latitude: float
    longitude: float
    elapsed_seconds: float


@dataclass(frozen=True)
class TransmissionPlan:
    points: list[TimedCoordinate]
    interval_seconds: float
    speed_kmh: float
    total_distance_meters: float


def haversine_meters(a: Coordinate, b: Coordinate) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    earth_radius_m = 6_371_000.0

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    r_lat1 = radians(lat1)
    r_lat2 = radians(lat2)

    h = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(h))


def route_distance_meters(points: Sequence[Coordinate]) -> float:
    return sum(haversine_meters(a, b) for a, b in zip(points, points[1:]))


def interpolate_route(
    route: Sequence[Coordinate],
    speed_kmh: float,
    interval_seconds: float = 1.0,
) -> list[TimedCoordinate]:
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be greater than zero")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if not route:
        return []
    if len(route) == 1:
        lat, lon = route[0]
        return [TimedCoordinate(lat, lon, 0.0)]

    speed_mps = speed_kmh * 1000.0 / 3600.0
    step_meters = speed_mps * interval_seconds
    cumulative = _cumulative_distances(route)
    total_distance = cumulative[-1]

    if total_distance == 0:
        lat, lon = route[0]
        return [TimedCoordinate(lat, lon, 0.0)]

    interpolated: list[TimedCoordinate] = []
    target_distance = 0.0
    while target_distance < total_distance:
        lat, lon = _point_at_distance(route, cumulative, target_distance)
        interpolated.append(
            TimedCoordinate(lat, lon, target_distance / speed_mps)
        )
        target_distance += step_meters

    end_lat, end_lon = route[-1]
    if not interpolated or (interpolated[-1].latitude, interpolated[-1].longitude) != route[-1]:
        interpolated.append(
            TimedCoordinate(end_lat, end_lon, total_distance / speed_mps)
        )

    return interpolated


def build_transmission_plan(
    route: Sequence[Coordinate],
    speed_kmh: float,
    interval_seconds: float = 1.0,
) -> TransmissionPlan:
    points = interpolate_route(route, speed_kmh, interval_seconds)
    return TransmissionPlan(
        points=points,
        interval_seconds=interval_seconds,
        speed_kmh=speed_kmh,
        total_distance_meters=route_distance_meters(route),
    )


def _cumulative_distances(points: Sequence[Coordinate]) -> list[float]:
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1] + haversine_meters(a, b))
    return distances


def _point_at_distance(
    points: Sequence[Coordinate],
    cumulative: Sequence[float],
    target_distance: float,
) -> Coordinate:
    if target_distance <= 0:
        return points[0]

    for index in range(1, len(cumulative)):
        segment_start = cumulative[index - 1]
        segment_end = cumulative[index]
        if target_distance <= segment_end:
            segment_distance = segment_end - segment_start
            if segment_distance == 0:
                return points[index]
            ratio = (target_distance - segment_start) / segment_distance
            lat1, lon1 = points[index - 1]
            lat2, lon2 = points[index]
            return (
                lat1 + (lat2 - lat1) * ratio,
                lon1 + (lon2 - lon1) * ratio,
            )

    return points[-1]


def normalize_coordinates(points: Iterable[Coordinate]) -> list[Coordinate]:
    return [(float(lat), float(lon)) for lat, lon in points]

