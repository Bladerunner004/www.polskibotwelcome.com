import io
import aiohttp
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
import datetime
from urllib.parse import urlparse

# --- KONFIGURACJA URL ---
# Wywoływana przy każdym użyciu fix_url, by mieć pewność że .env jest już załadowany
def _get_base_url():
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    if app_url:
        return app_url
    redirect_uri = os.environ.get("DISCORD_REDIRECT_URI", "")
    if redirect_uri:
        parsed = urlparse(redirect_uri)
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://BLADERUNNER009.pythonanywhere.com"

def fix_url(url):
    if not url: return url
    if isinstance(url, str):
        if url.startswith('http'): return url
        base = _get_base_url()
        if url.startswith('/static/'): return f"{base}{url}"
        if url.startswith('static/'): return f"{base}/{url}"
    return url

async def generate_framed_image(image_url, width=600, height=300, color=0x74b816, has_frame=True):
    """Generuje obraz idealnie dopasowany do ramki (Contain & Pad) z pełnym wsparciem dla animowanych GIF-ów."""
    try:
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        color_tuple = (r, g, b, 255)

        async with aiohttp.ClientSession() as session:
            async with session.get(fix_url(image_url)) as resp:
                if resp.status != 200: return None
                data = await resp.read()
                img = Image.open(io.BytesIO(data))
                
                # Determine scaling factor to fit within (width, height) preserving aspect ratio
                img_w, img_h = img.size
                ratio = min(width / img_w, height / img_h)
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                
                is_animated = getattr(img, "is_animated", False)
                if is_animated:
                    from PIL import ImageSequence
                    frames = []
                    durations = []
                    loop = img.info.get('loop', 0)
                    if not isinstance(loop, int) or loop is None:
                        loop = 0
                    global_duration = img.info.get('duration', 100)
                    
                    for frame in ImageSequence.Iterator(img):
                        p_frame = frame.convert("RGBA")
                        p_frame = p_frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        
                        if has_frame:
                            p_frame = ImageOps.expand(p_frame, border=10, fill=color_tuple)
                            canvas_width = width + 20
                        else:
                            canvas_width = width
                            
                        # Create transparent canvas
                        canvas = Image.new("RGBA", (canvas_width, p_frame.height), (0, 0, 0, 0))
                        x_offset = (canvas.width - p_frame.width) // 2
                        canvas.paste(p_frame, (x_offset, 0), p_frame)
                        
                        # Quantize for transparent GIF
                        alpha = canvas.split()[3]
                        canvas_p = canvas.convert('RGB').convert('P', palette=Image.Palette.ADAPTIVE, colors=255)
                        mask = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
                        canvas_p.paste(255, mask)
                        canvas_p.info['transparency'] = 255
                        
                        frames.append(canvas_p)
                        
                        dur = frame.info.get('duration')
                        if dur is None:
                            dur = global_duration
                        if not isinstance(dur, (int, float)) or dur <= 0:
                            dur = 100
                        durations.append(int(dur))
                    
                    buf = io.BytesIO()
                    frames[0].save(
                        buf,
                        format="GIF",
                        save_all=True,
                        append_images=frames[1:],
                        duration=durations,
                        loop=loop,
                        optimize=True,
                        disposal=2
                    )
                    buf.seek(0)
                    return buf, "gif"
                else:
                    img = img.convert("RGBA")
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    if has_frame:
                        img = ImageOps.expand(img, border=10, fill=color_tuple)
                        canvas_width = width + 20
                    else:
                        canvas_width = width
                        
                    canvas = Image.new("RGBA", (canvas_width, img.height), (0, 0, 0, 0))
                    x_offset = (canvas.width - img.width) // 2
                    canvas.paste(img, (x_offset, 0), img)
                    
                    buf = io.BytesIO()
                    canvas.save(buf, format="PNG")
                    buf.seek(0)
                    return buf, "png"
    except Exception as e:
        print(f"❌ [UTILS] Błąd generowania ramki: {e}")
        return None

async def generate_welcome_card(bg_url, avatar_url, line1, line2, font_name='arialbd.ttf', text_color='#ffffff', has_frame=0):
    """Generuje profesjonalną kartę powitalną (Cover & Center) z pełnym wsparciem dla animowanych GIF-ów."""
    try:
        width, height = 1000, 400
        bg = None
        
        # Pobieranie tła
        if bg_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(fix_url(bg_url)) as resp:
                    if resp.status == 200:
                        bg_data = await resp.read()
                        bg = Image.open(io.BytesIO(bg_data))
        
        # Pobieranie i formatowanie awatara (zawsze okrągły i wyśrodkowany)
        avatar = None
        avatar_mask = None
        if avatar_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(str(avatar_url).replace('.webp', '.png') + "?size=256") as resp:
                        if resp.status == 200:
                            avatar_data = await resp.read()
                            avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
                            avatar = avatar.resize((160, 160), Image.Resampling.LANCZOS)
                            avatar_mask = Image.new("L", (160, 160), 0)
                            ImageDraw.Draw(avatar_mask).ellipse((0, 0, 160, 160), fill=255)
            except Exception as ae:
                print(f"⚠️ [UTILS] Błąd pobierania awatara: {ae}")
        
        # Rysowanie tekstu i nakładanie awatara
        def load_smart_font(size):
            font_names = [font_name, "arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"]
            sys_paths = ["", "C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/"]
            for f in font_names:
                for p in sys_paths:
                    path = os.path.join(p, f)
                    if os.path.exists(path):
                        try: return ImageFont.truetype(path, size)
                        except: pass
            return ImageFont.load_default()

        f1 = load_smart_font(60)
        f2 = load_smart_font(40)
            
        def draw_frame_content(bg_frame):
            if avatar and avatar_mask:
                bg_frame.paste(avatar, (width // 2 - 80, 50), avatar_mask)
                
            draw = ImageDraw.Draw(bg_frame)
            def draw_center(text, y, font, color):
                bbox = draw.textbbox((0, 0), text, font=font)
                w = bbox[2] - bbox[0]
                draw.text((width // 2 - w/2, y), text, font=font, fill=color)

            draw_center(line1, 230, f1, text_color)
            draw_center(line2, 300, f2, text_color)
            
            # Ekskluzywna ramka (jeśli włączona)
            if has_frame:
                bg_frame = ImageOps.expand(bg_frame, border=10, fill=text_color)
            return bg_frame

        is_gif = bg is not None and getattr(bg, "is_animated", False)
        if is_gif:
            from PIL import ImageSequence
            frames = []
            durations = []
            loop = bg.info.get('loop', 0)
            if not isinstance(loop, int) or loop is None:
                loop = 0
            global_duration = bg.info.get('duration', 100)
            
            for frame in ImageSequence.Iterator(bg):
                p_frame = frame.convert("RGBA")
                p_frame = ImageOps.fit(p_frame, (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                p_frame = draw_frame_content(p_frame)
                frames.append(p_frame)
                
                dur = frame.info.get('duration')
                if dur is None:
                    dur = global_duration
                if not isinstance(dur, (int, float)) or dur <= 0:
                    dur = 100
                durations.append(int(dur))
                
            buf = io.BytesIO()
            frames[0].save(
                buf,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=loop,
                optimize=True,
                disposal=2
            )
            buf.seek(0)
            return buf, "gif"
        else:
            if not bg:
                bg = Image.new("RGBA", (width, height), (20, 22, 26, 255))
            else:
                bg = bg.convert("RGBA")
            
            bg = ImageOps.fit(bg, (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            bg = draw_frame_content(bg)
            
            buf = io.BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            return buf, "png"
    except Exception as e:
        print(f"❌ [UTILS] Błąd Pillow: {e}")
        return None
