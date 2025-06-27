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

        addOpenTypeFeatures(font, fea_file, ["GPOS"])

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
        self.height = 730

        self.output_image_path = output_image_path
        self.image = Image.new("RGB", (self.width, self.height), self.background_color)
        self.draw = ImageDraw.Draw(self.image)
        self.x = 20
        self.y = 20
        self.label_font = ImageFont.truetype("fonts/ETBookW-Bold.otf", 13)

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
    "source/ETBookOT-Italic.otf",
    "fonts/ETBookW-Italic.otf",
    "kerning-italic.fea",
)
adjuster.adjust("source/ETBookOT-Roman.otf", "fonts/ETBookW-Roman.otf")
adjuster.adjust("source/ETBookOT-Bold.otf", "fonts/ETBookW-Bold.otf")

renderer = ImageRenderer("example.png")

renderer.put_text("source/ETBookOT-Roman.otf", "Original Roman")
renderer.put_text("fonts/ETBookW-Roman.otf", "Modified Roman")
renderer.add_separator()

renderer.put_text("source/ETBookOT-Italic.otf", "Original Italic")
renderer.put_text("fonts/ETBookW-Italic.otf", "Modified Italic")
renderer.add_separator()

renderer.put_text("source/ETBookOT-Bold.otf", "Original Bold")
renderer.put_text("fonts/ETBookW-Bold.otf", "Modified Bold")

renderer.save()
