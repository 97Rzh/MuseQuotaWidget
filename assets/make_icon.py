"""画 MuseQuotaWidget 的图标，并生成 Mac iconset 与 Windows ICO。

设计（跟悬浮窗本体一致，不跟具体额度绑定，以免额度变了图标就过时）：
- 深色圆角方块，颜色就是悬浮窗卡片的 #1F2937；
- 中间一个绿色圆环，颜色就是剩余量 >=50% 时的 #4ADE80；
- 环里一个白色 %，代表“剩余额度百分比”。

只依赖 Pillow，跑一次生成：
- icon.png（1024x1024 主图）
- icon.iconset/（Mac iconutil 用的全套尺寸）
- icon.ico（Windows 用的多尺寸 ICO）

Mac 上生成 .icns 不在这里做：iconutil 是 macOS 自带的，
Linux 上没有，Mac 打包脚本 build_mac.sh 里会跑
iconutil -c icns assets/icon.iconset -o assets/icon.icns。
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024
BG = (31, 41, 55, 255)  # #1F2937，悬浮窗卡片色
GREEN = (74, 222, 128, 255)  # #4ADE80
WHITE = (255, 255, 255, 255)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_icon(size: int = SIZE) -> Image.Image:
    scale = size / SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆角方块：圆角半径约 22%，跟悬浮窗卡片圆角 16px 的感觉一致。
    radius = int(225 * scale)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG)
    # 绿色圆环：圆心略偏上，给下面留一点呼吸空间，环本身不画满到具体额度，
    # 只是一个“额度环”的示意，不会随真实额度过时。
    cx, cy = size // 2, int(480 * scale)
    r = int(300 * scale)
    w = int(72 * scale)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GREEN, width=w)
    # 环里白色 %：用大号粗体，居中。
    font = _font(int(360 * scale))
    text = "%"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=WHITE)
    # 下面一条小绿条：呼应悬浮窗底部的进度条，只是图形示意，
    # 绿段约 85% 宽，不代表实时额度，额度变了图标不用跟着换。
    bar_y0 = int(820 * scale)
    bar_h = int(44 * scale)
    bar_x0 = int(192 * scale)
    bar_x1 = int(832 * scale)
    draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y0 + bar_h], radius=bar_h // 2, fill=(255, 255, 255, 51))
    draw.rounded_rectangle([bar_x0, bar_y0, int(bar_x0 + (bar_x1 - bar_x0) * 0.85), bar_y0 + bar_h], radius=bar_h // 2, fill=GREEN)
    return img


def main() -> int:
    master = draw_icon(SIZE)
    master.save(os.path.join(ROOT, "icon.png"))
    # Mac iconset：标准命名，iconutil 靠这个认尺寸。
    iconset = os.path.join(ROOT, "icon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for name, px in [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]:
        master.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    # Windows ICO：Pillow 直接存多尺寸 ICO。
    master.save(os.path.join(ROOT, "icon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"wrote {os.path.join(ROOT, 'icon.png')}, {iconset}, {os.path.join(ROOT, 'icon.ico')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
