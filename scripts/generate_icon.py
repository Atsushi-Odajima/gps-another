from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def draw_icon(path: Path, size: int = 512) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor("#050505"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    scale = size / 512
    painter.scale(scale, scale)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ffffff"))

    # Stylized Japan silhouette. It is intentionally simple so it remains legible at icon sizes.
    hokkaido = QPainterPath()
    hokkaido.moveTo(330, 54)
    hokkaido.cubicTo(384, 48, 427, 76, 425, 118)
    hokkaido.cubicTo(416, 156, 358, 163, 326, 140)
    hokkaido.cubicTo(294, 118, 295, 72, 330, 54)
    painter.drawPath(hokkaido)

    honshu = QPainterPath()
    honshu.moveTo(307, 143)
    honshu.cubicTo(342, 164, 358, 199, 342, 228)
    honshu.cubicTo(320, 267, 269, 269, 248, 300)
    honshu.cubicTo(226, 333, 185, 332, 162, 358)
    honshu.cubicTo(146, 376, 116, 363, 122, 335)
    honshu.cubicTo(130, 302, 168, 293, 188, 269)
    honshu.cubicTo(218, 231, 218, 198, 248, 171)
    honshu.cubicTo(266, 154, 287, 142, 307, 143)
    painter.drawPath(honshu)

    shikoku = QPainterPath()
    shikoku.addRoundedRect(QRectF(206, 337, 90, 28), 14, 14)
    painter.drawPath(shikoku)

    kyushu = QPainterPath()
    kyushu.moveTo(126, 357)
    kyushu.cubicTo(166, 359, 183, 395, 169, 430)
    kyushu.cubicTo(154, 467, 99, 456, 91, 418)
    kyushu.cubicTo(84, 386, 99, 361, 126, 357)
    painter.drawPath(kyushu)

    okinawa_pen = QPen(QColor("#ffffff"), 10)
    okinawa_pen.setCapStyle(Qt.RoundCap)
    painter.setPen(okinawa_pen)
    painter.drawPoint(QPointF(66, 448))
    painter.drawPoint(QPointF(39, 466))

    painter.setPen(QColor("#ff941f"))
    font = QFont("Arial Black", 56)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
    painter.setFont(font)
    painter.drawText(QRectF(38, 424, 438, 80), Qt.AlignCenter, "MAPPP→")

    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))
    return image


def main() -> int:
    app = QGuiApplication(sys.argv)
    png = ASSETS / "app_icon.png"
    ico = ASSETS / "app_icon.ico"
    image = draw_icon(png)
    if not image.save(str(ico)):
        print(f"failed to save {ico}", file=sys.stderr)
        return 1
    print(png)
    print(ico)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
