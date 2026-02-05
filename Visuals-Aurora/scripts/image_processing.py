import os
import requests
from PIL import Image
from io import BytesIO
from colorthief import ColorThief


def download_image(job_folder, url, max_retries=3):
    image_path = os.path.join(job_folder, "cover.png")
    
    for attempt in range(max_retries):
        try:
            # Download image
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            
            # Load and convert to RGB
            img = Image.open(BytesIO(response.content)).convert("RGB")
            
            # Resize and crop to 700x700
            img = resize_and_crop(img, target_size=700)
            
            # Save
            img.save(image_path, format="PNG", optimize=True)
            
            print(f"✓ Image downloaded and processed")
            return image_path
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Image download failed (attempt {attempt + 1}/{max_retries}), retrying...")
            else:
                print(f"❌ Image download failed: {e}")
                raise
    
    return None


def resize_and_crop(img, target_size=700):
    w, h = img.size
    
    # Scale so smallest dimension = target
    scale = target_size / min(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    img = img.resize((new_w, new_h), Image.LANCZOS)
    
    # Center crop
    left = (new_w - target_size) // 2
    top = (new_h - target_size) // 2
    right = left + target_size
    bottom = top + target_size
    
    return img.crop((left, top, right, bottom))


def extract_colors(job_folder, color_count=2):
    image_path = os.path.join(job_folder, 'cover.png')
    
    if not os.path.exists(image_path):
        print(f"Cover image not found: {image_path}")
        return []
    
    try:
        # Extract palette
        color_thief = ColorThief(image_path)
        palette = color_thief.get_palette(color_count=color_count)
        
        # Convert RGB to hex
        colors_hex = [
            f'#{r:02x}{g:02x}{b:02x}'
            for r, g, b in palette
        ]
        
        print(f"✓ Extracted {len(colors_hex)} colors: {', '.join(colors_hex)}")
        return colors_hex
        
    except Exception as e:
        print(f"❌ Color extraction failed: {e}")
        # Return default colors as fallback
        return ['#ff5733', '#33ff57']