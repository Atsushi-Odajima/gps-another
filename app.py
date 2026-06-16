from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config import resource_path
from main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    icon_path = resource_path("assets/app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.resize(1180, 760)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
