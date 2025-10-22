from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
import os

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

W, H = 828, 1792  # iPhone-like size for a nice look
BG = (14, 19, 32)
CARD = (21, 29, 51)
TEXT = (230, 232, 242)
MUTED = (154, 163, 199)
ACCENT = (129, 107, 255)

try:
    FONT_BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    FONT_MED = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    FONT_SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
except Exception:
    FONT_BOLD = ImageFont.load_default()
    FONT_MED = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

def measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    # Pillow 10+: use textbbox instead of deprecated textsize
    bbox = draw.textbbox((0, 0), text, font=font)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])

# Header
margin = 48
y = margin

d.text((margin, y), "Checked Wallets", fill=MUTED, font=FONT_MED)
y += 60
d.text((margin, y), "1,165", fill=ACCENT, font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 92) if isinstance(FONT_BOLD, ImageFont.FreeTypeFont) else FONT_BOLD)
y += 120

d.text((margin, y), "Search results", fill=TEXT, font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40) if isinstance(FONT_BOLD, ImageFont.FreeTypeFont) else FONT_BOLD)
y += 36

# Result cards
card_w = W - margin * 2
card_h = 80
for i, line in enumerate([
    "Balance 0 | Wallet check | razor grit yard",
    "Balance 0 | Wallet check | wall issue ready",
    "Balance 0 | Wallet check | fuel luggage ramp",
]):
    top = y + 24 + i * (card_h + 20)
    d.rounded_rectangle((margin, top, margin + card_w, top + card_h), radius=18, fill=CARD)
    d.text((margin + 24, top + 22), line, fill=TEXT, font=FONT_SMALL)

y = y + 24 + 3 * (card_h + 20) + 12

# Token badges (simple circles with letters)
badges = [
    ("₿", (247, 147, 26)), ("Ξ", (98, 126, 234)), ("BNB", (243, 186, 47)), ("◎", (20, 241, 149)), ("AVA", (232, 65, 66)),
    ("Ł", (52, 92, 156)), ("OP", (255, 4, 32)), ("MATIC", (123, 63, 228)), ("TON", (19, 155, 208)), ("TRX", (197, 25, 39)),
]

r = 80
pad = 28
cols = 5
for idx, (txt, color) in enumerate(badges):
    row, col = divmod(idx, cols)
    cx = margin + col * ((card_w - r) // (cols - 1))
    cy = y + row * (r + pad)
    d.rounded_rectangle((cx, cy, cx + r, cy + r), radius=16, fill=CARD)
    tw, th = measure(d, txt, FONT_SMALL)
    d.text((cx + (r - tw) / 2, cy + (r - th) / 2), txt, fill=color, font=FONT_SMALL)

y += 2 * (r + pad) + 40

# Stop button
btn_h = 100
btn_rect = (margin, y, margin + card_w, y + btn_h)
d.rounded_rectangle(btn_rect, radius=24, fill=(255, 255, 255))
tw, th = measure(d, "Stop", FONT_MED)
d.text((margin + (card_w - tw) / 2, y + (btn_h - th) / 2), "Stop", fill=(11, 15, 26), font=FONT_MED)

y += btn_h + 80

# Bottom nav
nav_h = 100
d.rectangle((0, H - nav_h, W, H), fill=(11, 15, 26))
items = ["My profile", "Plans", "Support", "FAQ"]
for i, t in enumerate(items):
    tw, th = measure(d, t, FONT_SMALL)
    x = margin + i * ((W - 2 * margin) // (len(items) - 1))
    d.text((x - tw / 2, H - nav_h / 2 - th / 2), t, fill=MUTED, font=FONT_SMALL)

out = os.path.join(ASSETS_DIR, "mock_ui.png")
img.save(out)
print(f"Saved {out}")
