"""Erzeugt build/pausenpilot.ico (mehrere Größen, PNG-kodiert) aus dem gezeichneten App-Icon."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from pausenpilot.widgets import paint_app_icon  # noqa: E402


def main(out: Path):
    app = QGuiApplication(sys.argv)  # noqa: F841
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    blobs = []
    for s in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        paint_app_icon(s).save(buf, "PNG")
        blobs.append(bytes(ba))
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, b in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset + len(data))
        data += b
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + data)
    print("icon:", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "pausenpilot.ico")
