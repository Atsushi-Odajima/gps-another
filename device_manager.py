from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceStatus:
    detected: bool
    paired: bool
    developer_mode_assumed: bool
    connection: str
    detail: str
    identifier: str | None = None


class DeviceManager:
    def check_status(self) -> DeviceStatus:
        idevice_id = shutil.which("idevice_id")
        if idevice_id:
            return self._check_libimobiledevice(idevice_id)

        pymobiledevice3 = shutil.which("pymobiledevice3")
        if pymobiledevice3:
            return self._check_pymobiledevice3(pymobiledevice3)

        return DeviceStatus(
            detected=False,
            paired=False,
            developer_mode_assumed=True,
            connection="unknown",
            detail=(
                "idevice_id または pymobiledevice3 が見つかりません。"
                "USB 接続、信頼設定、Developer Mode、関連 CLI の導入を確認してください。"
            ),
        )

    def _check_libimobiledevice(self, executable: str) -> DeviceStatus:
        try:
            result = subprocess.run(
                [executable, "-l"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DeviceStatus(False, False, True, "usb", f"idevice_id 実行失敗: {exc}")

        identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not identifiers:
            detail = result.stderr.strip() or "iPhone が検出されませんでした"
            return DeviceStatus(False, False, True, "usb", detail)

        return DeviceStatus(
            detected=True,
            paired=True,
            developer_mode_assumed=True,
            connection="usb",
            detail="iPhone を検出しました。ペアリング済みとして扱います。",
            identifier=identifiers[0],
        )

    def _check_pymobiledevice3(self, executable: str) -> DeviceStatus:
        try:
            result = subprocess.run(
                [executable, "lockdown", "info"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DeviceStatus(False, False, True, "usb", f"pymobiledevice3 実行失敗: {exc}")

        output = result.stdout.strip()
        if result.returncode != 0:
            detail = result.stderr.strip() or output or "iPhone 情報を取得できませんでした"
            return DeviceStatus(False, False, True, "usb", detail)

        return DeviceStatus(
            detected=True,
            paired=True,
            developer_mode_assumed=True,
            connection="usb",
            detail="pymobiledevice3 で iPhone 情報を取得できました。",
        )

