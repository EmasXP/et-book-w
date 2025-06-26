from typing import Optional
from fontTools.ttLib import TTFont
from fontTools.feaLib.builder import addOpenTypeFeatures
from PIL import Image, ImageDraw, ImageFont


class FontAdjuster:
    def __init__(self, family_name: str):
        self.family_name = family_name

    def adjust(self, source: str, target: str, fea_file: str = "kerning.fea") -> None:
        font = TTFont(source)

        style_name: Optional[str] = None
        for record in font["name"].names:
            if record.nameID == 2:
                style_name = record.string.decode()
                break

        if style_name is None:
            raise ValueError("Style name not found in the font.")

        addOpenTypeFeatures(font, fea_file)
        for record in font["name"].names:
            if record.nameID == 1:
                record.string = self.family_name.encode("utf-16be")
            elif record.nameID == 2:
                record.string = style_name.encode("utf-16be")
            elif record.nameID == 4:
                record.string = f"{self.family_name} {style_name}".encode("utf-16be")
            elif record.nameID == 6:
                record.string = f"{self.family_name}-{style_name}".replace(
                    " ", ""
                ).encode("utf-16be")

        font.save(target)


class ImageRenderer:
    def __init__(self, output_image_path: str):
        self.background_color = "white"
        self.text_color = "black"
        self.text = "Wolverine Watermelon Yellow Avocado"
        self.width = 1050
        self.height = 980

        self.output_image_path = output_image_path
        self.image = Image.new("RGB", (self.width, self.height), self.background_color)
        self.draw = ImageDraw.Draw(self.image)
        self.x = 20
        self.y = 20
        self.label_font = ImageFont.truetype("fonts/ETBookW-SemiBoldOSF.otf", 13)

    def put_text(self, font_path: str, label: str) -> None:
        self.draw.text(
            (self.x, self.y), label, fill=self.text_color, font=self.label_font
        )
        self.y += 15

        font = ImageFont.truetype(font_path, 60)
        self.draw.text((self.x, self.y), self.text, fill=self.text_color, font=font)
        self.y += 90

    def add_separator(self) -> None:
        self.y += 40

    def save(self):
        self.image.save(self.output_image_path)


adjuster = FontAdjuster("ETBook W")
adjuster.adjust(
    "source/ETBembo-DisplayItalic.otf",
    "fonts/ETBookW-DisplayItalic.otf",
    "kerning-italic.tea",
)
adjuster.adjust("source/ETBembo-RomanLF.otf", "fonts/ETBookW-RomanLF.otf")
adjuster.adjust("source/ETBembo-RomanOSF.otf", "fonts/ETBookW-RomanOSF.otf")
adjuster.adjust("source/ETBembo-SemiBoldOSF.otf", "fonts/ETBookW-SemiBoldOSF.otf")

renderer = ImageRenderer("example.png")

renderer.put_text("source/ETBembo-RomanOSF.otf", "Original RomanOSF")
renderer.put_text("fonts/ETBookW-RomanOSF.otf", "Modified RomanOSF")
renderer.add_separator()

renderer.put_text("source/ETBembo-RomanLF.otf", "Original RomanLF")
renderer.put_text("fonts/ETBookW-RomanLF.otf", "Modified RomanLF")
renderer.add_separator()

renderer.put_text("source/ETBembo-DisplayItalic.otf", "Original RomanDisplayItalic")
renderer.put_text("fonts/ETBookW-DisplayItalic.otf", "Modified RomanDisplayItalic")
renderer.add_separator()

renderer.put_text("source/ETBembo-SemiBoldOSF.otf", "Original SemiBoldOSF")
renderer.put_text("fonts/ETBookW-SemiBoldOSF.otf", "Modified SemiBoldOSF")

renderer.save()
