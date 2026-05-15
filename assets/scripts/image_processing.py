"""
Image Processing - Download, resize, crop, vibrancy gate, and gradient builder
Shared across Aurora and Onyx templates (Mono doesn't use images)

Vibrancy gate (is_image_vibrant) rejects bland / grey / sepia covers so the
4-color gradient has actual colour to it. build_aurora_gradient picks a hero
colour and arranges the 4 gradient slots for maximum lyric contrast — the
default mode is "hero_dark" (slots 1+4 = saturated hero, slots 2+3 = near-black)
which is the pattern that worked best in production.
"""
import colorsys
import os
from urllib.parse import urlparse

import requests
from PIL import Image
from io import BytesIO
from colorthief import ColorThief

_ALLOWED_IMAGE_HOSTS = frozenset({
    "images.genius.com",
    "t2.genius.com",
    "assets.genius.com",
    "images.rapgenius.com",
    "s3.amazonaws.com",
})

# Vibrancy gate thresholds (HSV, 0-1 scale)
SATURATION_FLOOR = 0.30          # mean saturation across the image
GREY_CHANNEL_SPREAD = 25         # max(R,G,B) - min(R,G,B) for dominant colour
CHROMA_SPREAD_MIN = 40.0         # max distance in CIELAB a*/b* between palette cols
PALETTE_SAMPLE_COUNT = 6         # colours pulled from ColorThief for analysis
NEAR_BLACK = "#080810"           # slot 2/3 fill in hero_dark mode


def _validate_image_url(url: str) -> None:
    """Validate that the image URL is from a trusted host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Image URL must use http/https: {url}")
    if parsed.hostname and parsed.hostname not in _ALLOWED_IMAGE_HOSTS:
        raise ValueError(f"Image URL host not allowed: {parsed.hostname}")


def download_image(job_folder, url, max_retries=3):
    """Download and process cover image from URL"""
    _validate_image_url(url)
    image_path = os.path.join(job_folder, "cover.png")

    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            img = Image.open(BytesIO(response.content)).convert("RGB")
            img = resize_and_crop(img, target_size=700)
            img.save(image_path, format="PNG", optimize=True)

            print(f"✓ Image downloaded")
            return image_path

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries}...")
            else:
                print(f"❌ Image download failed: {e}")
                raise

    return None


def resize_and_crop(img, target_size=700):
    """Resize and center-crop image to target_size x target_size"""
    w, h = img.size

    scale = target_size / min(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_size) // 2
    top = (new_h - target_size) // 2
    right = left + target_size
    bottom = top + target_size

    return img.crop((left, top, right, bottom))


# ============================================================================
# VIBRANCY GATE
# ============================================================================

def _rgb_to_lab(r: int, g: int, b: int) -> tuple:
    """Approximate CIELAB conversion for chroma-spread distance comparisons."""
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    # Linearise sRGB
    def _lin(c: float) -> float:
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    rn, gn, bn = _lin(rn), _lin(gn), _lin(bn)
    # sRGB → XYZ (D65)
    x = rn * 0.4124 + gn * 0.3576 + bn * 0.1805
    y = rn * 0.2126 + gn * 0.7152 + bn * 0.0722
    z = rn * 0.0193 + gn * 0.1192 + bn * 0.9505
    # Normalise by D65 white
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883
    def _f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = _f(x), _f(y), _f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_ = 200 * (fy - fz)
    return (L, a, b_)


def _color_vibrancy(rgb: tuple) -> float:
    """Score a single colour. Higher = more vibrant (saturated + mid-luma)."""
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    # Penalise both very-dark and very-light colours
    luma_score = 1.0 - abs(l - 0.5) * 2
    return s * max(luma_score, 0.0)


def is_image_vibrant(image_path: str) -> tuple:
    """Return (ok: bool, info: dict). Rejects bland / grey / sepia covers.

    Three checks must all pass:
      1. Mean image saturation >= SATURATION_FLOOR (HSV space)
      2. Dominant palette colour has channel spread >= GREY_CHANNEL_SPREAD
      3. CIELAB a*/b* distance across palette >= CHROMA_SPREAD_MIN
    """
    info: dict = {}
    if not os.path.exists(image_path):
        return False, {"reason": "file missing"}

    try:
        img = Image.open(image_path).convert("HSV")
        # Compute mean saturation by sampling — full-image average is fine for 700x700
        pixels = list(img.getdata())
        if not pixels:
            return False, {"reason": "empty image"}
        mean_sat = sum(p[1] for p in pixels) / (len(pixels) * 255.0)
        info["mean_saturation"] = round(mean_sat, 3)
        if mean_sat < SATURATION_FLOOR:
            info["reason"] = f"low saturation ({mean_sat:.2f} < {SATURATION_FLOOR})"
            return False, info

        # Palette extraction
        thief = ColorThief(image_path)
        palette = thief.get_palette(color_count=PALETTE_SAMPLE_COUNT)
        if not palette:
            return False, {"reason": "no palette extracted", **info}

        dominant = palette[0]
        spread = max(dominant) - min(dominant)
        info["dominant_spread"] = spread
        info["dominant_hex"] = "#{:02x}{:02x}{:02x}".format(*dominant)
        if spread < GREY_CHANNEL_SPREAD:
            info["reason"] = f"dominant colour is grey (spread={spread} < {GREY_CHANNEL_SPREAD})"
            return False, info

        # Chroma spread across palette
        labs = [_rgb_to_lab(*c) for c in palette]
        max_dist = 0.0
        for i in range(len(labs)):
            for j in range(i + 1, len(labs)):
                da = labs[i][1] - labs[j][1]
                db = labs[i][2] - labs[j][2]
                d = (da * da + db * db) ** 0.5
                if d > max_dist:
                    max_dist = d
        info["chroma_spread"] = round(max_dist, 1)
        if max_dist < CHROMA_SPREAD_MIN:
            info["reason"] = (
                f"narrow palette range (chroma spread {max_dist:.1f} < {CHROMA_SPREAD_MIN})"
            )
            return False, info

        info["reason"] = "ok"
        return True, info

    except Exception as e:
        return False, {"reason": f"vibrancy check failed: {e}"}


# ============================================================================
# 4-COLOR GRADIENT BUILDER
# ============================================================================

def _hex(rgb: tuple) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def build_aurora_gradient(image_path: str) -> dict:
    """Build a 4-slot gradient list optimised for lyric contrast.

    Returns {"colors": [c1, c2, c3, c4], "mode": str, "hero": hex, "score": float}.
    Default mode is "hero_dark" (slots 1+4 = hero, slots 2+3 = near-black) when the
    most vibrant palette colour has saturation >= 0.6 — your Major-Lazer pattern.

    Falls back to two-tone (hero, secondary, hero, hero) when no colour is vibrant
    enough — better than nothing but the gate above should usually catch this.
    """
    if not os.path.exists(image_path):
        fallback = ["#ff5733", "#33ff57", "#ff5733", "#ff5733"]
        return {"colors": fallback, "mode": "fallback", "hero": fallback[0], "score": 0.0}

    try:
        thief = ColorThief(image_path)
        palette = thief.get_palette(color_count=PALETTE_SAMPLE_COUNT)
    except Exception as e:
        print(f"  ColorThief failed: {e}")
        fallback = ["#ff5733", "#33ff57", "#ff5733", "#ff5733"]
        return {"colors": fallback, "mode": "fallback", "hero": fallback[0], "score": 0.0}

    # Score every colour and sort by vibrancy
    scored = sorted(palette, key=_color_vibrancy, reverse=True)
    hero_rgb = scored[0]
    hero_score = _color_vibrancy(hero_rgb)
    hero_hex = _hex(hero_rgb)

    # Mode selection — hero_dark is preferred whenever the hero is saturated
    if hero_score >= 0.35:
        colors = [hero_hex, NEAR_BLACK, NEAR_BLACK, hero_hex]
        mode = "hero_dark"
    else:
        # Two-tone fallback — pick a contrasting secondary
        secondary_rgb = scored[1] if len(scored) > 1 else (20, 20, 30)
        secondary_hex = _hex(secondary_rgb)
        colors = [hero_hex, secondary_hex, secondary_hex, hero_hex]
        mode = "two_tone"

    print(f"✓ Gradient: mode={mode} hero={hero_hex} score={hero_score:.2f}")
    return {"colors": colors, "mode": mode, "hero": hero_hex, "score": round(hero_score, 3)}


def extract_colors(job_folder, color_count=2):
    """Extract a 4-slot gradient list for the job. Backwards-compatible shim:
    returns a list of hex strings (length 4) — callers don't need to know about
    the mode/hero metadata. For full metadata use build_aurora_gradient directly.
    """
    image_path = os.path.join(job_folder, 'cover.png')
    grad = build_aurora_gradient(image_path)
    return grad["colors"]
