"""Pillow steps: upscale the AI result and make the watermarked preview."""
import io
import math

from PIL import Image, ImageDraw, ImageFont, ImageOps

CLEAN_LONG_EDGE = 3000
PREVIEW_LONG_EDGE = 1600
API_LONG_EDGE = 1536
WATERMARK_TEXT = 'FavHost'
WATERMARK_OPACITY = 0.30
# Bump this whenever the watermark's look changes: stored previews carrying an older version are redrawn
# from the clean photo the next time they are shown (see views._current_preview_key).
WATERMARK_VERSION = 'w2'
_FONT_CANDIDATES = ('arialbd.ttf', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf')


def open_image(data):
    """Open + validate image bytes, honouring EXIF orientation."""
    img = Image.open(io.BytesIO(data))
    img.load()
    return ImageOps.exif_transpose(img)


def image_format(data):
    """Pillow's format name ('JPEG', 'PNG', ...) for image bytes."""
    with Image.open(io.BytesIO(data)) as img:
        return img.format


def to_png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def _to_rgb(img):
    if img.mode in ('RGBA', 'LA', 'P'):
        rgba = img.convert('RGBA')
        bg = Image.new('RGB', rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert('RGB')


def resize_long_edge(img, long_edge):
    """Resize keeping aspect ratio so the longer side is exactly `long_edge`."""
    w, h = img.size
    scale = long_edge / max(w, h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def prepare_for_api(img, long_edge=API_LONG_EDGE):
    """JPEG bytes for the edits call, shrunk so the longer side is <= 1536px.

    The API returns at most 1536px, so a bigger input only slows the upload and
    costs more input tokens; it never improves the result. Never upscales.
    """
    img = _to_rgb(img)
    if max(img.size) > long_edge:
        img = resize_long_edge(img, long_edge)
    return to_jpeg_bytes(img, 90)


def upscale_to_clean(img):
    return resize_long_edge(_to_rgb(img), CLEAN_LONG_EDGE)


def _font(size):
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def watermark(img):
    """Small, light, diagonal repeating white 'FavHost' text: visible enough to deter reuse, subtle enough
    that the photo is still clearly judged."""
    base = _to_rgb(img)
    if max(base.size) > PREVIEW_LONG_EDGE:  # preview never needs to be bigger than this
        base = resize_long_edge(base, PREVIEW_LONG_EDGE)
    base = base.convert('RGBA')
    w, h = base.size
    size = max(14, round(min(w, h) * 0.035))
    font = _font(size)
    alpha = round(255 * WATERMARK_OPACITY)
    stroke = 1   # hairline edge so the white text stays readable on bright walls

    left, top, right, bottom = font.getbbox(WATERMARK_TEXT, stroke_width=stroke)
    step_x, step_y = round((right - left) * 3.0), round((bottom - top) * 6.0)   # wide gaps: the photo stays easy to see

    # Draw on a square layer big enough that, once rotated, it still covers the photo.
    side = math.ceil(math.hypot(w, h))
    layer = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for row, y in enumerate(range(0, side, step_y)):
        offset = (step_x // 2) if row % 2 else 0
        for x in range(-step_x, side, step_x):
            draw.text((x + offset, y), WATERMARK_TEXT, font=font,
                      fill=(255, 255, 255, alpha), stroke_width=stroke, stroke_fill=(30, 30, 30, round(alpha * 0.45)))
    layer = layer.rotate(30, resample=Image.BICUBIC)
    crop_left, crop_top = (side - w) // 2, (side - h) // 2
    layer = layer.crop((crop_left, crop_top, crop_left + w, crop_top + h))
    return Image.alpha_composite(base, layer).convert('RGB')


def to_jpeg_bytes(img, quality):
    buf = io.BytesIO()
    # No optimize=True: it makes a 3000px encode noticeably slower for ~2% smaller files.
    img.save(buf, 'JPEG', quality=quality)
    return buf.getvalue()
