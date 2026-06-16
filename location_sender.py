from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SentLocation:
    latitude: float
    longitude: float
    sent_at: datetime


class LocationSender(ABC):
    @abstractmethod
    def send(self, latitude: float, longitude: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError


class MockLocationSender(LocationSender):
    def __init__(self) -> None:
        self.history: list[SentLocation] = []

    def send(self, latitude: float, longitude: float) -> None:
        sent = SentLocation(latitude, longitude, datetime.now())
        self.history.append(sent)
        print(
            f"[MOCK SEND] {sent.sent_at.isoformat(timespec='seconds')} "
            f"lat={latitude:.7f}, lon={longitude:.7f}",
            flush=True,
        )

    def clear(self) -> None:
        print("[MOCK CLEAR] simulated location cleared", flush=True)

