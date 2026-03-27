"""
Image Processing - Download, resize, crop, and color extraction
Shared across Aurora and Onyx templates (Mono doesn't use images)
"""
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


def extract_colors(job_folder, color_count=2):
    """Extract dominant colors from cover image"""
    image_path = os.path.join(job_folder, 'cover.png')
    
    if not os.path.exists(image_path):
        print(f"❌ Cover image not found")
        return ['#ff5733', '#33ff57']
    
    try:
        color_thief = ColorThief(image_path)
        palette = color_thief.get_palette(color_count=color_count)
        
        colors_hex = [
            f'#{r:02x}{g:02x}{b:02x}'
            for r, g, b in palette
        ]
        
        print(f"✓ Colors: {', '.join(colors_hex)}")
        return colors_hex
        
    except Exception as e:
        print(f"⚠️ Color extraction failed: {e}")
        return ['#ff5733', '#33ff57']
