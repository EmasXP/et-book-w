#!/usr/bin/env python3
"""
Kerning comparison GUI — ETBook W vs EB Garamond.

Lets you visually align a glyph pair, simulate GPOS kern in real time,
and copy the ready-to-paste kerning.fea snippet once you are happy.
"""

import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# ── Font discovery ────────────────────────────────────────────────────────────


def _fc_match(pattern: str) -> Optional[Path]:
    """Ask fontconfig for the best match. Returns None if fc-match unavailable."""
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{file}", pattern],
            capture_output=True,
            text=True,
            timeout=3,
        )
        path = Path(result.stdout.strip())
        if path.exists():
            return path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _scan_dirs(name_fragments: list[str]) -> Optional[Path]:
    """
    Walk common font directories and return the first file whose name
    contains *all* of the given fragments (case-insensitive).
    """
    search_dirs = [
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path("/Library/Fonts"),  # macOS
        Path.home() / "Library/Fonts",  # macOS user
        Path("C:/Windows/Fonts"),  # Windows
    ]
    fragments = [f.lower() for f in name_fragments]
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.?tf")):  # .otf and .ttf
            lower = p.name.lower()
            if all(f in lower for f in fragments):
                return p
    return None


def find_garamond(italic: bool = False) -> Optional[Path]:
    """
    Locate EB Garamond on the current system.
    Tries fc-match first, then directory scan, then a common-name guess.
    """
    style = "Italic" if italic else "Regular"
    fc_pattern = f"EB Garamond:style={style}"
    path = _fc_match(fc_pattern)
    if path and "garamond" in path.name.lower():
        return path

    # Directory scan: file must contain 'garamond' and the style keyword
    fragments = ["garamond", "italic" if italic else "regular"]
    path = _scan_dirs(fragments)
    if path:
        return path

    # Last resort: try the style without 'regular' (some distros omit it)
    if not italic:
        path = _scan_dirs(["ebgaramond", "regular"]) or _scan_dirs(["ebgaramond"])
    return path


# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent

GARAMOND_ROMAN_PATH: Optional[Path] = find_garamond(italic=False)
GARAMOND_ITALIC_PATH: Optional[Path] = find_garamond(italic=True)

if GARAMOND_ROMAN_PATH:
    print(f"EB Garamond Roman:  {GARAMOND_ROMAN_PATH}")
else:
    print(
        "WARNING: EB Garamond Roman not found — install the font or add it to ~/.fonts/"
    )

if GARAMOND_ITALIC_PATH:
    print(f"EB Garamond Italic: {GARAMOND_ITALIC_PATH}")
else:
    print(
        "WARNING: EB Garamond Italic not found — install the font or add it to ~/.fonts/"
    )

ETBOOK_SOURCE_ROMAN = SCRIPT_DIR / "source/ETBookOT-Roman.otf"
ETBOOK_SOURCE_ITALIC = SCRIPT_DIR / "source/ETBookOT-Italic.otf"

# ── Rendering constants (mirrored from garamond.py) ───────────────────────────
IMG_WIDTH = 1650
IMG_HEIGHT = 980
X_START = 100
Y_START = 20

ETBOOK_SIZE = 650
GARAMOND_ROMAN_SIZE = 655
GARAMOND_ITALIC_SIZE = 650

TOP_OFFSET_ROMAN = 80
TOP_OFFSET_ITALIC = 75

SQUEEZE_ITALIC = 0.93  # vertical squeeze applied to EB Garamond in italic mode
ETBOOK_COLOR = (105, 154, 70, 140)  # semi-transparent green overlay


# ── Font-metrics cache (avoid reloading TTFont on every render) ───────────────
_metrics_cache: dict[str, "FontMetrics"] = {}


class FontMetrics:
    """Thin wrapper around fontTools to look up glyph advance widths."""

    def __init__(self, path: str | Path) -> None:
        self._font = TTFont(str(path))
        self.upm: int = self._font["head"].unitsPerEm
        self._hmtx = self._font["hmtx"].metrics
        self._cmap: dict[int, str] = self._font.getBestCmap() or {}

    def glyph_name(self, char: str) -> Optional[str]:
        return self._cmap.get(ord(char))

    def advance_px(self, char: str, font_size: int) -> float:
        """Glyph advance width in pixels at PIL font_size."""
        name = self.glyph_name(char)
        if not name or name not in self._hmtx:
            return float(font_size)  # fallback: one em
        aw_uu, _ = self._hmtx[name]
        return aw_uu * font_size / self.upm

    def kern_px(self, kern_uu: int, font_size: int) -> float:
        """Convert design-unit kern value to pixels at PIL font_size."""
        return kern_uu * font_size / self.upm


def _get_metrics(path: str | Path) -> FontMetrics:
    key = str(path)
    if key not in _metrics_cache:
        _metrics_cache[key] = FontMetrics(path)
    return _metrics_cache[key]


# ── Core renderer ─────────────────────────────────────────────────────────────


def render_pair(
    char1: str,
    char2: str,
    alignment_offset: int,
    kern_value: int,
    italic: bool,
) -> QPixmap:
    """
    Render the comparison overlay for *char1 + char2* and return a QPixmap.

    Layout
    ──────
    • EB Garamond (black):   char1 at X_START, char2 at X_START + advance1_garamond
    • ETBook (green, semi-transparent):
          char1 at X_START + alignment_offset,
          char2 at X_START + alignment_offset + advance1_et + kern_px

    The kern simulation formula is:
        kern_px = kern_value × (font_size / UPM)
    which is the exact same linear mapping fontTools/feaLib uses when baking
    kern into the font.  So the value shown in the "Kern" spinbox goes directly
    into kerning.fea without any conversion.
    """
    garamond_path = GARAMOND_ITALIC_PATH if italic else GARAMOND_ROMAN_PATH
    etbook_path = ETBOOK_SOURCE_ITALIC if italic else ETBOOK_SOURCE_ROMAN
    garamond_size = GARAMOND_ITALIC_SIZE if italic else GARAMOND_ROMAN_SIZE
    top_offset = TOP_OFFSET_ITALIC if italic else TOP_OFFSET_ROMAN
    squeeze = SQUEEZE_ITALIC if italic else 1.0

    if garamond_path is None:
        style = "Italic" if italic else "Regular"
        return _error_pixmap(
            f"EB Garamond {style} not found on this system.\n"
            "Install it (e.g. apt install fonts-ebgaramond) or\n"
            "copy the .otf file into ~/.fonts/ and run fc-cache."
        )

    # PIL fonts
    try:
        pil_garamond = ImageFont.truetype(str(garamond_path), garamond_size)
        pil_etbook = ImageFont.truetype(str(etbook_path), ETBOOK_SIZE)
    except Exception as exc:
        return _error_pixmap(f"Font load error:\n{exc}")

    # fontTools metrics (only needed for kern unit→pixel conversion)
    try:
        et_m = _get_metrics(etbook_path)
    except Exception as exc:
        return _error_pixmap(f"Font metrics error:\n{exc}")

    image = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (255, 255, 255, 255))

    # ── EB Garamond layer (black) ────────────────────────────────────────────
    # Draw as ONE string so FreeType applies EB Garamond's own GPOS kern.
    # This is the "ground truth" spacing we're trying to match in ETBook.
    garam_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(garam_layer)
    gd.text((X_START, Y_START), char1 + char2, fill="black", font=pil_garamond)

    if squeeze != 1.0:
        orig_w, orig_h = garam_layer.size
        new_h = int(orig_h * squeeze)
        garam_layer = garam_layer.resize((orig_w, new_h), Image.Resampling.LANCZOS)
        y_paste = (IMG_HEIGHT - new_h) // 2
        image.paste(garam_layer, (0, y_paste), garam_layer)
    else:
        image.paste(garam_layer, (0, 0), garam_layer)

    # ── ETBook layer (semi-transparent green) with kern simulation ────────────
    et_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    ed = ImageDraw.Draw(et_layer)
    et_x = X_START + alignment_offset
    et_y = Y_START + top_offset
    ed.text((et_x, et_y), char1, fill=ETBOOK_COLOR, font=pil_etbook)
    adv1_et = pil_etbook.getlength(char1)  # use PIL/FreeType advance, not hmtx
    kern_shift = et_m.kern_px(kern_value, ETBOOK_SIZE)
    ed.text(
        (et_x + adv1_et + kern_shift, et_y), char2, fill=ETBOOK_COLOR, font=pil_etbook
    )

    image.paste(et_layer, (0, 0), et_layer)

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    try:
        small_font = ImageFont.truetype(str(etbook_path), 28)
    except Exception:
        small_font = ImageFont.load_default()
    ld = ImageDraw.Draw(legend_layer)
    mode_label = "Italic" if italic else "Roman"
    ld.text(
        (X_START, IMG_HEIGHT - 50),
        "■ EB Garamond",
        fill=(0, 0, 0, 200),
        font=small_font,
    )
    ld.text(
        (X_START + 300, IMG_HEIGHT - 50),
        "■ ETBook W",
        fill=ETBOOK_COLOR,
        font=small_font,
    )
    ld.text(
        (X_START + 560, IMG_HEIGHT - 50),
        mode_label,
        fill=(150, 150, 150, 200),
        font=small_font,
    )
    image.paste(legend_layer, (0, 0), legend_layer)

    return _pil_to_qpixmap(image)


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    pixmap = QPixmap()
    pixmap.loadFromData(buf.read())
    return pixmap


def _error_pixmap(message: str) -> QPixmap:
    img = Image.new("RGBA", (IMG_WIDTH, 200), (255, 240, 240, 255))
    d = ImageDraw.Draw(img)
    d.text((20, 20), message, fill=(180, 0, 0, 255))
    return _pil_to_qpixmap(img)


# ── Preview builder ───────────────────────────────────────────────────────────


def build_preview_font(g1: str, g2: str, kern_value: int, italic: bool) -> Path:
    """
    Patch the live kerning.fea with *kern_value* for the (g1, g2) pair,
    inject it into the source font, and write to a temporary .otf.
    Returns the path to the temporary font file.
    The caller is responsible for deleting it when done.
    """
    from fontTools.feaLib.builder import addOpenTypeFeatures

    source_path = ETBOOK_SOURCE_ITALIC if italic else ETBOOK_SOURCE_ROMAN
    fea_path = SCRIPT_DIR / ("kerning-italic.fea" if italic else "kerning.fea")

    with open(fea_path) as f:
        fea_content = f.read()

    # Replace existing pair or inject before the closing "} kern;"
    new_rule = f"\tpos {g1} {g2} {kern_value};"
    pattern = re.compile(
        rf"(\tpos\s+{re.escape(g1)}\s+{re.escape(g2)}\s+)(-?\d+)(;)"
    )
    if pattern.search(fea_content):
        fea_content = pattern.sub(rf"\g<1>{kern_value}\g<3>", fea_content)
    else:
        fea_content = fea_content.replace("} kern;", f"{new_rule}\n}} kern;")

    # Write patched .fea to a temp file
    tmp_fea = tempfile.NamedTemporaryFile(
        mode="w", suffix=".fea", delete=False, prefix="etbook_preview_"
    )
    tmp_fea.write(fea_content)
    tmp_fea.close()

    # Build font into a second temp file
    tmp_otf = tempfile.NamedTemporaryFile(
        suffix=".otf", delete=False, prefix="etbook_preview_"
    )
    tmp_otf.close()

    font = TTFont(str(source_path))
    addOpenTypeFeatures(font, tmp_fea.name, ["GPOS"])
    font.save(tmp_otf.name)

    # Clean up temp .fea; caller cleans up the .otf
    Path(tmp_fea.name).unlink(missing_ok=True)

    return Path(tmp_otf.name)


def render_preview_from_font(
    char1: str,
    char2: str,
    alignment_offset: int,
    font_path: Path,
    italic: bool,
) -> QPixmap:
    """
    Render the overlay using the already-built preview font.
    Both fonts are drawn as a single string so FreeType applies GPOS kern natively.
    """
    garamond_path = GARAMOND_ITALIC_PATH if italic else GARAMOND_ROMAN_PATH
    garamond_size = GARAMOND_ITALIC_SIZE if italic else GARAMOND_ROMAN_SIZE
    top_offset = TOP_OFFSET_ITALIC if italic else TOP_OFFSET_ROMAN
    squeeze = SQUEEZE_ITALIC if italic else 1.0

    if garamond_path is None:
        style = "Italic" if italic else "Roman"
        return _error_pixmap(
            f"EB Garamond {style} not found.\n"
            "Install it or copy the .otf to ~/.fonts/ and run fc-cache."
        )

    try:
        pil_garamond = ImageFont.truetype(str(garamond_path), garamond_size)
        pil_etbook = ImageFont.truetype(str(font_path), ETBOOK_SIZE)
    except Exception as exc:
        return _error_pixmap(f"Font load error:\n{exc}")

    image = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (255, 255, 255, 255))

    # ── EB Garamond (black) — string render, FreeType applies its own kern ────
    garam_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(garam_layer)
    gd.text((X_START, Y_START), char1 + char2, fill="black", font=pil_garamond)

    if squeeze != 1.0:
        orig_w, orig_h = garam_layer.size
        new_h = int(orig_h * squeeze)
        garam_layer = garam_layer.resize((orig_w, new_h), Image.Resampling.LANCZOS)
        y_paste = (IMG_HEIGHT - new_h) // 2
        image.paste(garam_layer, (0, y_paste), garam_layer)
    else:
        image.paste(garam_layer, (0, 0), garam_layer)

    # ── ETBook preview (green) — string render, FreeType applies GPOS kern ────
    et_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    ed = ImageDraw.Draw(et_layer)
    ed.text(
        (X_START + alignment_offset, Y_START + top_offset),
        char1 + char2,
        fill=ETBOOK_COLOR,
        font=pil_etbook,
    )
    image.paste(et_layer, (0, 0), et_layer)

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_layer = Image.new("RGBA", (IMG_WIDTH, IMG_HEIGHT), (0, 0, 0, 0))
    try:
        small_font = ImageFont.truetype(str(font_path), 28)
    except Exception:
        small_font = ImageFont.load_default()
    ld = ImageDraw.Draw(legend_layer)
    mode_label = "Italic" if italic else "Roman"
    ld.text((X_START, IMG_HEIGHT - 50), "■ EB Garamond", fill=(0, 0, 0, 200), font=small_font)
    ld.text((X_START + 300, IMG_HEIGHT - 50), "■ ETBook W (built)", fill=ETBOOK_COLOR, font=small_font)
    ld.text((X_START + 610, IMG_HEIGHT - 50), mode_label, fill=(150, 150, 150, 200), font=small_font)
    image.paste(legend_layer, (0, 0), legend_layer)

    return _pil_to_qpixmap(image)


# ── Preview window ────────────────────────────────────────────────────────────


class PreviewWindow(QDialog):
    """Modal window showing the built-font overlay."""

    def __init__(self, pixmap: QPixmap, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Preview — {label}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        img_label = QLabel()
        img_label.setPixmap(pixmap)
        img_label.resize(pixmap.size())
        scroll.setWidget(img_label)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Size the dialog to fit the image, capped at 90% of the screen
        screen = QApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * 0.9)
        max_h = int(screen.height() * 0.9)
        self.resize(min(pixmap.width() + 40, max_w), min(pixmap.height() + 80, max_h))


# ── Widgets ───────────────────────────────────────────────────────────────────


class SingleCharEdit(QLineEdit):
    """QLineEdit restricted to one character, with a larger font."""

    def __init__(self, default: str = "A", parent: Optional[QWidget] = None) -> None:
        super().__init__(default, parent)
        self.setMaxLength(1)
        self.setFixedWidth(52)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.font()
        font.setPointSize(20)
        self.setFont(font)


# ── Main window ───────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ETBook Kerning Comparator")

        # Debounce timer — re-renders 300 ms after the last control change
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._refresh)

        self._build_ui()
        self._schedule_refresh()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Row 1: pair input + mode toggle ──────────────────────────────────
        row1 = QHBoxLayout()
        root.addLayout(row1)

        row1.addWidget(QLabel("Pair:"))
        self.char1_edit = SingleCharEdit("A")
        self.char2_edit = SingleCharEdit("T")
        row1.addWidget(self.char1_edit)
        row1.addWidget(self.char2_edit)

        row1.addSpacing(24)

        self.italic_check = QCheckBox("Italic")
        row1.addWidget(self.italic_check)

        row1.addStretch()

        # ── Row 2: scrollable image area ──────────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setMinimumHeight(380)
        self.image_label = QLabel()
        self.image_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.scroll.setWidget(self.image_label)
        root.addWidget(self.scroll, stretch=1)

        # ── Row 3: alignment + kern controls ─────────────────────────────────
        row3 = QHBoxLayout()
        root.addLayout(row3)

        row3.addWidget(QLabel("Alignment offset (px):"))
        self.align_spin = QSpinBox()
        self.align_spin.setRange(-500, 500)
        self.align_spin.setValue(0)
        self.align_spin.setFixedWidth(90)
        self.align_spin.setToolTip(
            "Shift the ETBook overlay horizontally so the first\n"
            "character of both fonts lines up visually."
        )
        row3.addWidget(self.align_spin)

        row3.addSpacing(24)

        row3.addWidget(QLabel("Kern value (design units):"))
        self.kern_spin = QSpinBox()
        self.kern_spin.setRange(-1000, 1000)
        self.kern_spin.setValue(0)
        self.kern_spin.setFixedWidth(90)
        self.kern_spin.setToolTip(
            "Kern pair adjustment in font design units.\n"
            "Negative = tighter, positive = looser.\n"
            "This value goes directly into kerning.fea."
        )
        row3.addWidget(self.kern_spin)

        row3.addStretch()

        # ── Row 4: FEA snippet + copy + refresh ──────────────────────────────
        row4 = QHBoxLayout()
        root.addLayout(row4)

        row4.addWidget(QLabel("FEA snippet:"))

        self.fea_edit = QLineEdit()
        self.fea_edit.setReadOnly(True)
        self.fea_edit.setFixedWidth(260)
        mono = self.fea_edit.font()
        mono.setFamily("monospace")
        mono.setPointSize(12)
        self.fea_edit.setFont(mono)
        self.fea_edit.setToolTip("Copy this line into kerning.fea")
        row4.addWidget(self.fea_edit)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(self._copy_fea)
        row4.addWidget(copy_btn)

        row4.addSpacing(20)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self._refresh)
        row4.addWidget(refresh_btn)

        row4.addSpacing(8)

        self.preview_btn = QPushButton("Preview (build)")
        self.preview_btn.setFixedWidth(120)
        self.preview_btn.setToolTip(
            "Build a temporary font with the current kern value\n"
            "and render the pair using FreeType's native GPOS kern.\n"
            "This is the ground-truth check — identical to build.py."
        )
        self.preview_btn.clicked.connect(self._show_preview)
        row4.addWidget(self.preview_btn)

        row4.addStretch()

        # ── Wire up auto-refresh ──────────────────────────────────────────────
        self.char1_edit.textChanged.connect(self._schedule_refresh)
        self.char2_edit.textChanged.connect(self._schedule_refresh)
        self.italic_check.stateChanged.connect(self._schedule_refresh)
        self.align_spin.valueChanged.connect(self._schedule_refresh)
        self.kern_spin.valueChanged.connect(self._schedule_refresh)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        self._timer.start()

    def _refresh(self) -> None:
        char1 = self.char1_edit.text()
        char2 = self.char2_edit.text()
        if not char1 or not char2:
            return

        italic = self.italic_check.isChecked()
        alignment = self.align_spin.value()
        kern = self.kern_spin.value()

        pixmap = render_pair(char1, char2, alignment, kern, italic)
        self.image_label.setPixmap(pixmap)
        self.image_label.resize(pixmap.size())

        # Build FEA snippet with proper OpenType glyph names
        etbook_path = ETBOOK_SOURCE_ITALIC if italic else ETBOOK_SOURCE_ROMAN
        g1 = self._glyph_name(etbook_path, char1) or char1
        g2 = self._glyph_name(etbook_path, char2) or char2
        self.fea_edit.setText(f"\tpos {g1} {g2} {kern};")

    def _glyph_name(self, font_path: Path, char: str) -> Optional[str]:
        try:
            return _get_metrics(font_path).glyph_name(char)
        except Exception:
            return None

    def _show_preview(self) -> None:
        char1 = self.char1_edit.text()
        char2 = self.char2_edit.text()
        if not char1 or not char2:
            return

        italic = self.italic_check.isChecked()
        alignment = self.align_spin.value()
        kern = self.kern_spin.value()

        # Resolve glyph names for the pair
        etbook_path = ETBOOK_SOURCE_ITALIC if italic else ETBOOK_SOURCE_ROMAN
        g1 = self._glyph_name(etbook_path, char1) or char1
        g2 = self._glyph_name(etbook_path, char2) or char2

        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("Building…")
        QApplication.processEvents()

        tmp_font: Optional[Path] = None
        try:
            tmp_font = build_preview_font(g1, g2, kern, italic)
            pixmap = render_preview_from_font(char1, char2, alignment, tmp_font, italic)
            label = f"{char1}{char2}  kern={kern}  {'Italic' if italic else 'Roman'}"
            dlg = PreviewWindow(pixmap, label, parent=self)
            dlg.exec()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Preview failed", str(exc))
        finally:
            if tmp_font and tmp_font.exists():
                tmp_font.unlink(missing_ok=True)
            self.preview_btn.setEnabled(True)
            self.preview_btn.setText("Preview (build)")

    # ── Clipboard ─────────────────────────────────────────────────────────────

    def _copy_fea(self) -> None:
        text = self.fea_edit.text().strip()
        QApplication.clipboard().setText(text)


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1100, 780)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
