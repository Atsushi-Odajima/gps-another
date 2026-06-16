from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    ors_api_key: str
    graphhopper_api_key: str
    route_timeout_seconds: int = 30
    send_interval_seconds: float = 1.0
    min_speed_kmh: int = 1
    max_speed_kmh: int = 40
    max_points: int = 4
    default_speed_kmh: int = 5

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            ors_api_key=os.getenv("ORS_API_KEY", "").strip(),
            graphhopper_api_key=os.getenv("GRAPHHOPPER_API_KEY", "").strip(),
        )


CONFIG = AppConfig.from_env()

