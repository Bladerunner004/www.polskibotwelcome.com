import io
import aiohttp
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
import datetime

# --- KONFIGURACJA URL ---
BASE_URL = "https://BLADERUNNER009.pythonanywhere.com"

def fix_url(url):
    if not url: return url
    if isinstance(url, str):
        if url.startswith('http'): return url
        if url.startswith('/static/'): return f"{BASE_URL}{url}"
        if url.startswith('static/'): return f"{BASE_URL}/{url}"
    return url

async def generate_framed_image(image_url, width=600, height=300):
    """Generuje obraz idealnie dopasowany do ramki (Crop & Center)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(fix_url(image_url)) as resp:
                if resp.status != 200: return None
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                
                # Inteligentne dopasowanie: Wypełnij ramkę i wyśrodkuj (Cover)
                img = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                return buf
    except Exception as e:
        print(f"❌ [UTILS] Błąd generowania ramki: {e}")
        return None

async def generate_welcome_card(bg_url, avatar_url, line1, line2, font_name='arialbd.ttf', text_color='#ffffff', has_frame=0):
    """Generuje profesjonalną kartę powitalną."""
    try:
        width, height = 1000, 400
        bg = None
        
        # Pobieranie tła
        if bg_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(fix_url(bg_url)) as resp:
                    if resp.status == 200:
                        bg = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
        
        if not bg: bg = Image.new("RGBA", (width, height), (20, 22, 26, 255))
        bg = ImageOps.fit(bg, (width, height), Image.Resampling.LANCZOS)
        
        # Pobieranie i formatowanie awatara
        async with aiohttp.ClientSession() as session:
            async with session.get(str(avatar_url).replace('.webp', '.png') + "?size=256") as resp:
                if resp.status == 200:
                    avatar = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                    avatar = avatar.resize((160, 160), Image.Resampling.LANCZOS)
                    mask = Image.new("L", (160, 160), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 160, 160), fill=255)
                    bg.paste(avatar, (width // 2 - 80, 50), mask)
        
        # Rysowanie tekstu
        draw = ImageDraw.Draw(bg)
        try:
            # Fallback czcionek dla różnych systemów
            font_path = font_name if os.path.exists(font_name) else "arialbd.ttf"
            f1 = ImageFont.truetype(font_path, 60)
            f2 = ImageFont.truetype(font_path, 40)
        except:
            f1 = ImageFont.load_default()
            f2 = ImageFont.load_default()
            
        def draw_center(text, y, font, color):
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            draw.text((width // 2 - w/2, y), text, font=font, fill=color)

        draw_center(line1, 230, f1, text_color)
        draw_center(line2, 300, f2, text_color)
        
        if has_frame: bg = ImageOps.expand(bg, border=10, fill=text_color)

        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"❌ [UTILS] Błąd Pillow: {e}")
        return None
