import sys
# Ustawienie kodowania dla Windows, aby uniknąć UnicodeEncodeError przy printowaniu emoji
if sys.platform == 'win32':
    import io
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass
    try: sys.stderr.reconfigure(encoding='utf-8')
    except: pass

import discord
from discord.ext import commands, tasks
from discord import ui
import datetime
import asyncio
import os
import random
import aiohttp
from dotenv import load_dotenv
import re
import json
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Ścieżka do statusu (dla PythonAnywhere)
STATUS_FILE_PATH = "/home/BLADERUNNER009/AntigravityProjekt/bot_status.json"
if not os.path.exists("/home/BLADERUNNER009"):
    STATUS_FILE_PATH = "bot_status.json" # Fallback lokalny

# --- GLOBALNA LISTA ZAKAZANYCH SŁÓW (Wulgaryzmy, Rasizm, Toksyczność) ---
GLOBAL_BADWORDS = [
    "kurwa", "chuj", "pizda", "jebac", "pierdol", "cwel", "pedal", "czarnuch", "nigger", "huj", 
    "suka", "dziwka", "kutas", "fiut", "szmata", "frajer", "zjeb", "debil", "idiota", "cipa",
    "skurwysyn", "pierdole", "jebie", "pizdziel", "kutasie", "fiucie", "pedale", "cwelu",
    "k.u.r.w.a", "k_u_r_w_a", "k u r w a", "kurw@", "k0rwa", "j3bac", "jeb@c", "p3dal",
    "faggot", "retard", "nigga", "bitch", "slut", "whore", "asshole", "dick", "pussy",
    "spierdalaj", "zamknij sie", "morda", "konfident", "pedaly", "jebane", "pierdolone",
    "cipsko", "ruchanie", "ruchac", "stuleja", "zjebie", "ryj", "suczo", "kurew"
]

def check_badwords(text, custom_words=None):
    text = text.lower()
    # Uproszczona normalizacja (usuwanie znaków interpunkcyjnych i spacji między literami)
    normalized = re.sub(r'[^a-ząćęłńóśźż]', '', text)
    
    # Łączymy globalną listę z listą serwera
    words_to_check = GLOBAL_BADWORDS
    if custom_words and isinstance(custom_words, list):
        words_to_check = words_to_check + custom_words

    for word in words_to_check:
        word = word.lower()
        # Sprawdzanie bezpośrednie
        if word in text: return True
        # Sprawdzanie znormalizowane (wykrywa k u r w a, k.u.r.w.a itp)
        clean_word = re.sub(r'[^a-ząćęłńóśźż]', '', word)
        if clean_word and clean_word in normalized: return True
    return False

# Importy z bazy danych z zabezpieczeniem
try:
    from database import (
        is_command_enabled, get_welcome_configs, get_prefix, get_settings, 
        save_member_roles, get_member_roles, update_counter_channel_id, 
        get_role_counters, update_role_counter_channel_id, get_selfrole_configs, 
        sync_selfrole_configs, log_message_activity, log_join_activity,
        get_media_configs
    )
except ImportError:
    print("⚠️ Nie udało się zaimportować funkcji z database.py. Używam fallbacków.")
    def is_command_enabled(guild_id, cmd_name): return True
    def get_welcome_configs(guild_id, config_type): return []
    def get_prefix(guild_id): return "!"

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

def get_dynamic_prefix(bot, message):
    if not message.guild:
        return "!"
    return get_prefix(str(message.guild.id))

bot = commands.Bot(command_prefix=get_dynamic_prefix, intents=intents)

# --- WIDOK WERYFIKACJI LINKU ---
class LinkReviewView(ui.View):
    def __init__(self, target_message):
        super().__init__(timeout=None)
        self.target_message = target_message

    @ui.button(label="✅ Bezpieczny", style=discord.ButtonStyle.success)
    async def safe(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.message.delete()

    @ui.button(label="❌ Niebezpieczny (Usuń)", style=discord.ButtonStyle.danger)
    async def danger(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        try:
            await self.target_message.delete()
            await interaction.response.send_message(f"🗑️ Usunięto niebezpieczny link od **{self.target_message.author}**.", ephemeral=True)
        except: pass
        await interaction.message.delete()

# --- POMOCNICZA FUNKCJA: Pobieranie koloru bota dla serwera ---
def get_embed_color(guild):
    """Pobiera kolor embedu z bazy (lub losuje RGB)."""
    try:
        if not guild: return 0x74b816
        from database import get_settings
        settings = get_settings(str(guild.id))
        
        # Pierwszeństwo ma tryb RGB
        if settings.get('rgb_mode'):
            return discord.Color.from_rgb(
                random.randint(0, 255), 
                random.randint(0, 255), 
                random.randint(0, 255)
            )
        
        color_hex = settings.get('embed_color', '#74b816').replace('#', '')
        return int(color_hex, 16)
    except Exception as e:
        return 0x74b816

# --- POMOCNICZA FUNKCJA: Czy komenda jest włączona? ---
async def check_command(ctx, command_name):
    if not ctx.guild:
        return True
    
    # Master switch dla moderacji
    mod_cmds = ["ban", "kick", "mute", "unban", "unmute", "warn", "warns", "clear", "slowmode", "modinfo", "temprole", "votemute", "massrole"]
    if command_name in mod_cmds:
        settings = get_settings(str(ctx.guild.id))
        if not settings.get("moderation_enabled", True):
            await reply(ctx, "⚠️ System moderacji jest obecnie wyłączony w panelu.")
            return False

    # Przekazujemy ID serwera do sprawdzenia w bazie
    if not is_command_enabled(str(ctx.guild.id), command_name):
        await reply(ctx, f"⚠️ Komenda `/{command_name}` jest obecnie wyłączona w panelu sterowania.")
        return False
    return True

# --- WIDOK POTWIERDZENIA MODERACJI ---
class ConfirmModeration(ui.View):
    def __init__(self, target, action_name, user):
        super().__init__(timeout=30)
        self.target = target
        self.action_name = action_name
        self.user = user
        self.confirmed = False

    @ui.button(label="✅ Potwierdzam", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ Tylko autor komendy może to potwierdzić!", ephemeral=True)
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content=f"⏳ Przetwarzanie akcji: **{self.action_name}**...", view=None)

    @ui.button(label="❌ Anuluj", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ Tylko autor komendy może to anulować!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="❌ Akcja została anulowana.", view=None)

# --- POMOCNICZA FUNKCJA ODPOWIEDZI ---
async def reply(ctx, content=None, embed=None, ephemeral=True):
    if ctx.interaction:
        if not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await ctx.send(content=content, embed=embed)

# --- WIDOK TICKETA ---
class TicketActions(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🙋 Przejmij", style=discord.ButtonStyle.green, custom_id="claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, view_channel=True)
        await interaction.channel.send(f"🙋 **{interaction.user.display_name}** przejął to zgłoszenie!")
        await interaction.response.edit_message(view=self)

    @ui.button(label="🔒 Zamknij", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Brak uprawnień!", ephemeral=True)
        await interaction.response.send_message("🔒 Zgłoszenie zostanie zamknięte.")
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}")
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)

# --- KOMENDY ---

@bot.hybrid_command(name="ticket", description="Otwórz nowe zgłoszenie.")
async def ticket(ctx, tytul: str, sprawa: str):
    if not await check_command(ctx, "ticket"): return
    if ctx.interaction: await ctx.interaction.response.defer(ephemeral=True)
    
    channel_name = f"ticket-{ctx.author.name.lower()}".replace(" ", "-")
    channel = await ctx.guild.create_text_channel(
        channel_name, 
        overwrites={
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, view_channel=True)
        }
    )
    
    embed = discord.Embed(title=f"📢 {tytul}", description=f"Witaj {ctx.author.mention}!\n\n**Sprawa:** {sprawa}", color=get_embed_color(ctx.guild))
    embed.set_footer(text="Polski Bot • System Zgłoszeń")
    await channel.send(embed=embed, view=TicketActions())
    await reply(ctx, f"✅ Otwarto zgłoszenie: {channel.mention}")

@bot.hybrid_command(name="level", description="Sprawdź swój poziom.")
async def level(ctx, uzytkownik: discord.Member = None):
    if not await check_command(ctx, "level"): return
    uzytkownik = uzytkownik or ctx.author
    await reply(ctx, f"📊 {uzytkownik.display_name} posiada obecnie **1 Level**.")

@bot.hybrid_command(name="ban", description="Zbanuj użytkownika.")
@commands.has_permissions(ban_members=True)
async def ban(ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
    if not await check_command(ctx, "ban"): return
    
    settings = get_settings(str(ctx.guild.id))
    if settings.get("moderation_confirm"):
        view = ConfirmModeration(uzytkownik, "BAN", ctx.author)
        msg = await ctx.send(f"🛡️ **POTWIERDZENIE:** Czy na pewno chcesz zbanować użytkownika {uzytkownik.mention}?\n**Powód:** {powod}", view=view)
        await view.wait()
        if not view.confirmed: return
    
    try:
        await uzytkownik.ban(reason=powod)
        await reply(ctx, f"🔨 Zbanowano {uzytkownik.mention}. Powód: {powod}")
    except Exception as e:
        await reply(ctx, f"❌ Błąd podczas banowania: {e}")

@bot.hybrid_command(name="kick", description="Wyrzuć użytkownika.")
@commands.has_permissions(kick_members=True)
async def kick(ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
    if not await check_command(ctx, "kick"): return
    
    settings = get_settings(str(ctx.guild.id))
    if settings.get("moderation_confirm"):
        view = ConfirmModeration(uzytkownik, "KICK", ctx.author)
        msg = await ctx.send(f"🛡️ **POTWIERDZENIE:** Czy na pewno chcesz wyrzucić użytkownika {uzytkownik.mention}?\n**Powód:** {powod}", view=view)
        await view.wait()
        if not view.confirmed: return
        
    try:
        await uzytkownik.kick(reason=powod)
        await reply(ctx, f"👢 Wyrzucono {uzytkownik.mention}. Powód: {powod}")
    except Exception as e:
        await reply(ctx, f"❌ Błąd podczas wyrzucania: {e}")

@bot.hybrid_command(name="mute", description="Wycisz użytkownika.")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, uzytkownik: discord.Member, minuty: int, *, powod: str = "Brak"):
    if not await check_command(ctx, "mute"): return
    duration = datetime.timedelta(minutes=minuty)
    await uzytkownik.timeout(duration, reason=powod)
    await reply(ctx, f"🔇 Wyciszono {uzytkownik.mention} na {minuty} min.")

@bot.hybrid_command(name="unmute", description="Odwycisz użytkownika.")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, uzytkownik: discord.Member):
    if not await check_command(ctx, "unmute"): return
    await uzytkownik.timeout(None)
    await reply(ctx, f"🔊 Odwyciszono {uzytkownik.mention}.")

@bot.hybrid_command(name="unban", description="Odbanuj użytkownika (ID).")
@commands.has_permissions(ban_members=True)
async def unban(ctx, id_uzytkownika: str):
    if not await check_command(ctx, "unban"): return
    user = await bot.fetch_user(id_uzytkownika)
    await ctx.guild.unban(user)
    await reply(ctx, f"✅ Odbanowano użytkownika o ID {id_uzytkownika}.")

@bot.hybrid_command(name="warn", description="Daj ostrzeżenie użytkownikowi.")
@commands.has_permissions(kick_members=True)
async def warn(ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
    if not await check_command(ctx, "warn"): return
    await reply(ctx, f"⚠️ Ostrzeżono {uzytkownik.mention}. Powód: {powod}")

@bot.hybrid_command(name="warns", description="Sprawdź ostrzeżenia użytkownika.")
async def warns(ctx, uzytkownik: discord.Member = None):
    if not await check_command(ctx, "warns"): return
    uzytkownik = uzytkownik or ctx.author
    await reply(ctx, f"📋 {uzytkownik.display_name} posiada obecnie **0** ostrzeżeń.")

@bot.hybrid_command(name="slowmode", description="Ustaw slowmode na kanale.")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, sekundy: int):
    if not await check_command(ctx, "slowmode"): return
    await ctx.channel.edit(slowmode_delay=sekundy)
    await reply(ctx, f"🐢 Ustawiono slowmode na **{sekundy}s**.")

@bot.hybrid_command(name="toplevel", description="Zobacz ranking poziomów.")
async def toplevel(ctx):
    if not await check_command(ctx, "toplevel"): return
    await reply(ctx, "🏆 **Ranking Poziomów:**\n1. " + ctx.author.name + " - 1 LVL")

@bot.hybrid_command(name="exp", description="Sprawdź ile masz punktów doświadczenia.")
async def exp(ctx):
    if not await check_command(ctx, "exp"): return
    await reply(ctx, f"✨ Masz obecnie **0 EXP**.")

@bot.hybrid_command(name="modinfo", description="Informacje o moderatorze.")
async def modinfo(ctx, moderator: discord.Member):
    if not await check_command(ctx, "modinfo"): return
    await reply(ctx, f"🛡️ **Moderator:** {moderator.mention}\nAkcji: 0")

@bot.hybrid_command(name="temprole", description="Nadaj rolę na czas.")
@commands.has_permissions(manage_roles=True)
async def temprole(ctx, uzytkownik: discord.Member, rola: discord.Role, czas: str):
    if not await check_command(ctx, "temprole"): return
    await reply(ctx, f"⏳ Nadano rolę {rola.name} użytkownikowi {uzytkownik.mention} na {czas}.")

@bot.hybrid_command(name="votemute", description="Głosowanie za wyciszeniem.")
async def votemute(ctx, uzytkownik: discord.Member):
    if not await check_command(ctx, "votemute"): return
    await reply(ctx, f"🗳️ Rozpoczęto głosowanie za wyciszeniem {uzytkownik.mention}!")

@bot.hybrid_command(name="massrole", description="Nadaj rolę wszystkim.")
@commands.has_permissions(administrator=True)
async def massrole(ctx, rola: discord.Role):
    if not await check_command(ctx, "massrole"): return
    await reply(ctx, f"🎭 Rozpoczęto nadawanie roli {rola.name} wszystkim użytkownikom...")

@bot.hybrid_command(name="unclaim", description="Zwolnij przejęte zgłoszenie.")
async def unclaim(ctx):
    if not await check_command(ctx, "unclaim"): return
    await reply(ctx, "🙋 Zgłoszenie zostało zwolnione.")

@bot.hybrid_command(name="claim", description="Przejmij zgłoszenie.")
async def claim(ctx):
    if not await check_command(ctx, "claim"): return
    if not ctx.channel.name.startswith("ticket-"):
        return await reply(ctx, "❌ Ta komenda działa tylko na kanałach zgłoszeń!")
    await ctx.channel.set_permissions(ctx.author, read_messages=True, send_messages=True, view_channel=True)
    await reply(ctx, f"🙋 **{ctx.author.display_name}** przejął to zgłoszenie!")

@bot.hybrid_command(name="close", description="Zamknij zgłoszenie.")
async def close(ctx):
    if not await check_command(ctx, "close"): return
    await reply(ctx, "🔒 Zgłoszenie zostanie zamknięte.")

@bot.hybrid_command(name="pomoc", description="Lista wszystkich komend bota.")
async def pomoc(ctx):
    if not await check_command(ctx, "pomoc"): return
    embed = discord.Embed(title="📖 Lista komend Polski Bot", color=get_embed_color(ctx.guild))
    embed.add_field(name="🎟️ Zgłoszenia", value="`/ticket` `/claim` `/close` `/unclaim`", inline=False)
    embed.add_field(name="🛡️ Moderacja", value="`/ban` `/unban` `/kick` `/mute` `/unmute` `/warn` `/warns` `/clear` `/slowmode` `/modinfo` `/temprole` `/votemute` `/massrole`", inline=False)
    embed.add_field(name="📊 Poziomy", value="`/level` `/toplevel` `/exp`", inline=False)
    embed.add_field(name="🎮 Zabawa", value="`/iq` `/cat` `/meme` `/slap`", inline=False)
    embed.add_field(name="ℹ️ Systemowe", value="`/info` `/pomoc`", inline=False)
    embed.set_footer(text="Polski Bot • polskibot.pl")
    await reply(ctx, embed=embed, ephemeral=False)

@bot.hybrid_command(name="clear", description="Usuń wiadomości z kanału.")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, ilosc: int):
    if not await check_command(ctx, "clear"): return
    await ctx.channel.purge(limit=ilosc + 1)
    await reply(ctx, f"🧹 Usunięto **{ilosc}** wiadomości.", ephemeral=True)

@bot.hybrid_command(name="iq", description="Sprawdź swoje IQ.")
async def iq(ctx):
    if not await check_command(ctx, "iq"): return
    wynik = random.randint(50, 150)
    await reply(ctx, f"🧠 Twoje IQ wynosi: **{wynik}**!")

@bot.hybrid_command(name="cat", description="Losowe zdjęcie kota.")
async def cat(ctx):
    if not await check_command(ctx, "cat"): return
    async with aiohttp.ClientSession() as session:
        async with session.get('https://api.thecatapi.com/v1/images/search') as resp:
            data = await resp.json()
            embed = discord.Embed(title="🐱 Losowy kotek!", color=get_embed_color(ctx.guild))
            embed.set_image(url=data[0]['url'])
            await reply(ctx, embed=embed)

@bot.hybrid_command(name="meme", description="Losowy mem.")
async def meme(ctx):
    if not await check_command(ctx, "meme"): return
    async with aiohttp.ClientSession() as session:
        async with session.get('https://meme-api.com/gimme') as resp:
            data = await resp.json()
            embed = discord.Embed(title=data['title'], color=get_embed_color(ctx.guild))
            embed.set_image(url=data['url'])
            await reply(ctx, embed=embed)

@bot.hybrid_command(name="slap", description="Uderz kogoś!")
async def slap(ctx, uzytkownik: discord.Member):
    if not await check_command(ctx, "slap"): return
    await reply(ctx, f"✋ {ctx.author.mention} uderzył {uzytkownik.mention}! Ałć!")

@bot.hybrid_command(name="info", description="O bocie.")
async def info(ctx):
    embed = discord.Embed(
        title="🤖 Polski Bot",
        description="Zaawansowany bot do zarządzania serwerem.\n\n🌐 [Panel WWW](https://polskibot.pl)\n💬 [Support](https://discord.gg/G5F3WBbZ)",
        color=get_embed_color(ctx.guild)
    )

    embed.add_field(name="🏠 Serwery", value=f"{len(bot.guilds)}", inline=True)
    embed.add_field(name="⚡ Ping", value=f"{round(bot.latency * 1000)}ms", inline=True)
    await reply(ctx, embed=embed, ephemeral=False)

# --- OBSŁUGA ZDARZEŃ I GENEROWANIE OBRAZKA ---

async def create_welcome_image(bg_url, avatar_url, line1, line2, font_name='arialbd.ttf', text_color='#ffffff', has_frame=0):
    """Generuje obrazek powitalny z awatarem i tekstem przy użyciu Pillow."""
    try:
        bg = None
        width, height = 1000, 400
        
        # 1. POBIERANIE TŁA
        # ... (pobieranie tła bez zmian) ...
        # 1. POBIERANIE TŁA
        if bg_url:
            if bg_url.startswith('http'):
                # Zdalny URL
                async with aiohttp.ClientSession() as session:
                    async with session.get(bg_url) as resp:
                        if resp.status == 200:
                            bg_data = await resp.read()
                            bg = Image.open(io.BytesIO(bg_data)).convert("RGBA")
            else:
                # Lokalna ścieżka (np. /static/uploads/...)
                # Czyścimy ścieżkę, aby pasowała do struktury plików
                local_path = bg_url.lstrip('/')
                if os.path.exists(local_path):
                    bg = Image.open(local_path).convert("RGBA")
                elif os.path.exists(os.path.join('static', 'uploads', os.path.basename(bg_url))):
                    bg = Image.open(os.path.join('static', 'uploads', os.path.basename(bg_url))).convert("RGBA")
        
        # Jeśli tła nadal brak, stwórz ciemny, profesjonalny baner
        if not bg:
            bg = Image.new("RGBA", (width, height), (20, 22, 26, 255))
        
        # Zmień rozmiar tła (Crop & Fill zamiast spłaszczania)
        bg = ImageOps.fit(bg, (width, height), Image.Resampling.LANCZOS)
        
        # 2. POBIERANIE AWATARA
        async with aiohttp.ClientSession() as session:
            try:
                # Wymuszamy format PNG dla awatara, aby PIL go obsłużył
                clean_avatar_url = str(avatar_url).split('?')[0]
                if clean_avatar_url.endswith('.webp'):
                    clean_avatar_url = clean_avatar_url.replace('.webp', '.png')
                
                async with session.get(clean_avatar_url + "?size=256") as resp:
                    if resp.status == 200:
                        avatar_data = await resp.read()
                        avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
                    else:
                        avatar = Image.new("RGBA", (256, 256), (100, 100, 100, 255))
            except:
                avatar = Image.new("RGBA", (256, 256), (100, 100, 100, 255))
        
        # Wytnij kółko z awatara
        size = (160, 160)
        avatar = avatar.resize(size, Image.Resampling.LANCZOS)
        mask = Image.new("L", size, 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0) + size, fill=255)
        
        # Wklej awatar na środek
        bg.paste(avatar, (width // 2 - 80, 50), mask)
        
        # 3. RYSOWANIE TEKSTU
        draw = ImageDraw.Draw(bg)
        
        # Konwersja koloru HEX na RGB
        try:
            h = text_color.lstrip('#')
            rgb_color = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        except:
            rgb_color = (255, 255, 255)

        # Próba załadowania wybranej czcionki
        try:
            # Sprawdzamy czy to pełna ścieżka, jeśli nie - szukamy w Windows/Fonts
            font_path = font_name
            if not os.path.exists(font_path):
                win_font = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'Fonts', font_name)
                if os.path.exists(win_font):
                    font_path = win_font
            
            f1 = ImageFont.truetype(font_path, 60)
            f2 = ImageFont.truetype(font_path, 40)
        except Exception as e:
            print(f"⚠️ [BOT] Błąd ładowania czcionki {font_name}: {e}. Używam fallbacku.")
            try:
                f1 = ImageFont.truetype("arialbd.ttf", 60)
                f2 = ImageFont.truetype("arial.ttf", 40)
            except:
                f1 = ImageFont.load_default()
                f2 = ImageFont.load_default()
            
        def draw_center(draw, text, y, font, color):
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            draw.text((width // 2 - w/2, y), text, font=font, fill=color)

        draw_center(draw, line1, 230, f1, rgb_color)
        draw_center(draw, line2, 300, f2, rgb_color)
        
        # DODAWANIE RAMKI
        if has_frame:
            from PIL import ImageOps
            bg = ImageOps.expand(bg, border=10, fill=text_color)

        # Zapisz do bufora
        buffer = io.BytesIO()
        # Jeśli tło to GIF i chcemy animację, to Pillow PNG tego nie zachowa.
        # Ale dla powitań generujemy statyczny obrazek "powitalny".
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"❌ [BOT] Błąd PIL: {e}")
        return None

async def send_welcome_message(guild: discord.Guild, member: discord.Member, config_type: str, target_id=None):
    configs = get_welcome_configs(str(guild.id), config_type)
    if not configs: return

    # Jeśli podano target_id, filtrujemy tylko tę jedną konfigurację
    if target_id is not None:
        configs = [c for c in configs if str(c['id']) == str(target_id)]
        if not configs: return

    tag_map = {
        "{nick}": member.name,
        "{mention}": member.mention,
        "{tag}": str(member),
        "{server}": guild.name,
        "{count}": str(guild.member_count),
    }

    # Zabezpieczenie przed podwójnym wysyłaniem na ten sam kanał w jednym evencie
    sent_channels = set()

    for cfg in configs:
        # SPRAWDZANIE CZY KONFIGURACJA JEST WŁĄCZONA
        if not cfg.get('is_enabled', 1):
            continue

        ch_id_str = str(cfg.get('channel_id', ''))
        if ch_id_str in sent_channels: continue
        
        channel = guild.get_channel(int(ch_id_str)) if ch_id_str.isdigit() else None
        if not channel: continue
        
        print(f"[DEBUG] Wysyłanie {config_type} (ID: {cfg.get('id')}) na kanał {channel.name}")
        sent_channels.add(ch_id_str)
        
        embed_color = get_embed_color(guild)

        content = (cfg.get('plain_text') or '')
        for tag, val in tag_map.items(): content = content.replace(tag, val)

        try:
            embed = None
            if cfg.get('is_embed'):
                desc = (cfg.get('description') or '')
                for tag, val in tag_map.items(): desc = desc.replace(tag, val)
                
                title = (cfg.get('title') or '')
                for tag, val in tag_map.items(): title = title.replace(tag, val)
                
                footer = (cfg.get('footer') or '')
                for tag, val in tag_map.items(): footer = footer.replace(tag, val)
                
                author_text = (cfg.get('author') or '')
                for tag, val in tag_map.items(): author_text = author_text.replace(tag, val)

                embed = discord.Embed(color=embed_color)
                
                # 1. AUTOR (Na samej górze - ikona mała, awatar bota lub pusta)
                if author_text:
                    embed.set_author(name=author_text) # Usuwamy icon_url stąd, aby nie było "miniaturek"

                # 2. TYTUŁ
                if title:
                    embed.title = title
                
                # 3. OPIS
                if desc:
                    embed.description = desc
                
                # 4. STOPKA
                if footer:
                    embed.set_footer(text=footer)
                
            # PRZYGOTOWANIE OBRAZKA (Dla obu trybów: Embed i Zwykły)
            file = None
            if cfg.get('has_image'):
                bg_url = cfg.get('bg_url', '')
                
                # Tryb GIF
                if bg_url.lower().endswith('.gif'):
                    try:
                        if bg_url.startswith('http'):
                            async with aiohttp.ClientSession() as session:
                                async with session.get(bg_url) as resp:
                                    if resp.status == 200:
                                        file = discord.File(fp=io.BytesIO(await resp.read()), filename="welcome.gif")
                        else:
                            local_path = bg_url.lstrip('/')
                            if os.path.exists(local_path):
                                file = discord.File(fp=local_path, filename="welcome.gif")
                        
                        if file and embed:
                            embed.set_image(url="attachment://welcome.gif")
                    except: pass
                
                # Tryb Obrazek (Generowany)
                if not file:
                    line1 = (cfg.get('line1') or 'WITAJ')
                    line2 = (cfg.get('line2') or '{nick}')
                    for tag, val in tag_map.items(): line1 = line1.replace(tag, val)
                    for tag, val in tag_map.items(): line2 = line2.replace(tag, val)
                    
                    img_buffer = await create_welcome_image(
                        bg_url, 
                        member.display_avatar.url, 
                        line1, line2,
                        font_name=cfg.get('font_name', 'arialbd.ttf'),
                        text_color=cfg.get('img_text_color', '#ffffff'),
                        has_frame=cfg.get('has_frame', 0)
                    )
                    if img_buffer:
                        file = discord.File(fp=img_buffer, filename="welcome.png")
                        if embed:
                            embed.set_image(url="attachment://welcome.png")

            # WYSYŁANIE KOŃCOWE
            if embed:
                await channel.send(content=content if content else None, embed=embed, file=file)
            else:
                await channel.send(content=content if content else None, file=file)
        except Exception as e:
            print(f"⚠️ [POWITANIA] Błąd: {e}")

@bot.event
async def on_member_update(before, after):
    # Wykrywanie boosta
    if not before.premium_since and after.premium_since:
        # Ktoś właśnie zaczął ulepszać
        settings = get_settings(str(after.guild.id))
        booster_roles = settings.get("autorole_booster_roles", [])
        roles_to_add = []
        for rid in booster_roles:
            role = after.guild.get_role(int(rid))
            if role: roles_to_add.append(role)
        if roles_to_add:
            try:
                await after.add_roles(*roles_to_add, reason="Nowy Booster!")
                print(f"🚀 [AUTOROLE] Booster {after.name} — nadano role: {[r.name for r in roles_to_add]}")
            except Exception as e:
                print(f"❌ [AUTOROLE] Błąd nadawania ról boosterowi {after.name}: {e}")
            
    elif before.premium_since and not after.premium_since:
        # Ktoś przestał ulepszać
        settings = get_settings(str(after.guild.id))
        if settings.get("autorole_booster_remove", True):
            booster_roles = settings.get("autorole_booster_roles", [])
            roles_to_remove = []
            for rid in booster_roles:
                role = after.guild.get_role(int(rid))
                if role and role in after.roles: roles_to_remove.append(role)
            if roles_to_remove:
                try:
                    await after.remove_roles(*roles_to_remove, reason="Koniec ulepszania")
                    print(f"📤 [AUTOROLE] Ex-booster {after.name} — usunięto role: {[r.name for r in roles_to_remove]}")
                except Exception as e:
                    print(f"❌ [AUTOROLE] Błąd usuwania ról ex-boosterowi {after.name}: {e}")

async def sync_booster_roles(guild):
    """Synchronizuje role u obecnych boosterów na serwerze."""
    from database import get_settings
    settings = get_settings(str(guild.id))
    booster_roles_ids = settings.get("autorole_booster_roles", [])
    booster_remove = settings.get("autorole_booster_remove", True)
    
    roles_to_set = []
    for rid in booster_roles_ids:
        try:
            role = guild.get_role(int(rid))
            if role: roles_to_set.append(role)
        except: pass
        
    if not roles_to_set and not booster_remove: return

    print(f"🔄 [AUTOROLE] Rozpoczynam synchronizację boosterów na {guild.name}...")
    for member in guild.members:
        # Sprawdzamy czy jest boosterem (premium_since nie jest None)
        if member.premium_since:
            to_add = [r for r in roles_to_set if r not in member.roles]
            if to_add:
                try: 
                    await member.add_roles(*to_add, reason="Synchronizacja ról boostera")
                    print(f"  + Nadano role boosterowi {member.name}")
                except: pass
        elif booster_remove:
            # Jeśli nie jest boosterem, a opcja usuwania jest włączona
            to_remove = [r for r in roles_to_set if r in member.roles]
            if to_remove:
                try: 
                    await member.remove_roles(*to_remove, reason="Synchronizacja ról boostera (usunięcie)")
                    print(f"  - Usunięto role ex-boosterowi {member.name}")
                except: pass
    print(f"✅ [AUTOROLE] Synchronizacja boosterów na {guild.name} zakończona.")

# Blokada zapobiegająca jednoczesnym aktualizacjom liczników na tym samym serwerze
counter_locks = {}

async def update_counters(guild):
    if not guild: return
    guild_id = str(guild.id)
    
    if guild_id not in counter_locks:
        counter_locks[guild_id] = asyncio.Lock()
    
    async with counter_locks[guild_id]:
        settings = get_settings(guild_id)
        print(f"📊 [COUNTERS] Akcja dla {guild.name}")
        
        async def process_counter(type_key, enabled, name_format, current_id, pos):
            is_enabled = bool(enabled)
            
            # --- 1. WYŁĄCZANIE LICZNIKA ---
            if not is_enabled:
                if current_id and str(current_id).strip():
                    channel = guild.get_channel(int(current_id))
                    if channel:
                        try: 
                            await channel.delete(reason="Licznik wyłączony w panelu")
                            print(f"   - Usunięto kanał {type_key}")
                        except: pass
                    # ZAWSZE czyścimy ID w bazie przy wyłączaniu
                    update_counter_channel_id(guild.id, type_key, None)
                return

            # --- 2. LICZNIK WŁĄCZONY - SPRAWDZANIE KANAŁU ---
            count = 0
            if type_key == "humans":
                count = sum(1 for m in guild.members if not m.bot)
            elif type_key == "bots":
                count = sum(1 for m in guild.members if m.bot)
            elif type_key == "bans":
                try:
                    # Szybszy sposób na zliczanie banów (limit 1000 dla stabilności)
                    ban_count = 0
                    async for _ in guild.bans(limit=1000):
                        ban_count += 1
                    count = ban_count
                except: count = 0
            
            new_name = name_format.replace("{count}", str(count))
            
            channel = None
            if current_id and str(current_id).strip() and str(current_id) != "None":
                try:
                    channel = guild.get_channel(int(current_id))
                except ValueError:
                    pass
                
                # Jeśli ID istnieje w bazie, ale kanału NIE MA na serwerze
                if not channel:
                    print(f"   - Kanał {type_key} zniknął z serwera. Czyszczę pamięć.")
                    update_counter_channel_id(guild.id, type_key, None)
            
            # --- 3. PRÓBA ODNALEZIENIA PO NAZWIE (zabezpieczenie przed dublami) ---
            if not channel:
                prefix = name_format.split('{count}')[0]
                for vch in guild.voice_channels:
                    if vch.name.startswith(prefix):
                        channel = vch
                        update_counter_channel_id(guild.id, type_key, channel.id)
                        print(f"   - Odnaleziono istniejący kanał: {vch.name}. Podpinam ID.")
                        break

            # --- 4. TWORZENIE NOWEGO KANAŁU ---
            if not channel:
                try:
                    channel = await guild.create_voice_channel(
                        name=new_name,
                        overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)},
                        position=pos,
                        reason=f"Tworzenie licznika {type_key}"
                    )
                    update_counter_channel_id(guild.id, type_key, channel.id)
                    print(f"   ✅ Stworzono NOWY kanał {type_key}: {new_name}")
                except Exception as e:
                    print(f"   ❌ Błąd tworzenia {type_key}: {e}")
            
            # --- 5. AKTUALIZACJA NAZWY ---
            elif channel.name != new_name:
                try: 
                    await channel.edit(name=new_name)
                    print(f"   ✅ Zaktualizowano {type_key} -> {new_name}")
                except: pass

        # Procesowanie każdego licznika
        await process_counter("humans", settings.get("counter_humans_enabled"), settings.get("counter_humans_name", "Humans: {count}"), settings.get("counter_humans_channel_id"), 0)
        await process_counter("bots", settings.get("counter_bots_enabled"), settings.get("counter_bots_name", "Bots: {count}"), settings.get("counter_bots_channel_id"), 1)
        await process_counter("bans", settings.get("counter_bans_enabled"), settings.get("counter_bans_name", "Bans: {count}"), settings.get("counter_bans_channel_id"), 2)

    # 4. LICZENIE KONKRETNYCH RÓL (DYNAMICZNE)
    role_configs = get_role_counters(guild.id)
    for cfg in role_configs:
        is_enabled = cfg.get('enabled', 1)
        channel_id = cfg.get('channel_id')
        
        if is_enabled:
            count = 0
            target_role_ids = [int(rid) for rid in cfg['roles']]
            if cfg['mode'] == 'white':
                members = set()
                for rid in target_role_ids:
                    role = guild.get_role(rid)
                    if role:
                        for m in role.members: members.add(m.id)
                count = len(members)
            else:
                blacklisted_members = set()
                for rid in target_role_ids:
                    role = guild.get_role(rid)
                    if role:
                        for m in role.members: blacklisted_members.add(m.id)
                all_humans = sum(1 for m in guild.members if not m.bot)
                count = max(0, all_humans - len(blacklisted_members))

            name_format = cfg['name'] or "Role: {count}"
            new_name = name_format.replace("{count}", str(count))
            
            channel = None
            if channel_id and str(channel_id).strip() and str(channel_id) != "None":
                try:
                    channel = guild.get_channel(int(channel_id))
                except ValueError:
                    pass
            
            if not channel:
                try:
                    channel = await guild.create_voice_channel(
                        name=new_name,
                        overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)},
                        position=3,
                        reason="Dynamiczny licznik ról"
                    )
                    from database import update_role_counter_channel_id
                    update_role_counter_channel_id(cfg['id'], channel.id)
                except: pass
            elif channel.name != new_name:
                try: await channel.edit(name=new_name)
                except: pass
        elif channel_id and str(channel_id).strip() and str(channel_id) != "None":
            try:
                channel = guild.get_channel(int(channel_id))
                if channel:
                    await channel.delete(reason="Dynamiczny licznik wyłączony")
                from database import update_role_counter_channel_id
                update_role_counter_channel_id(cfg['id'], None)
            except: 
                pass

@bot.event
async def on_member_ban(guild, user):
    await update_counters(guild)

@bot.event
async def on_member_unban(guild, user):
    await update_counters(guild)

@bot.event
async def on_member_join(member):
    print(f"📥 [EVENT] Nowy użytkownik dołączył: {member.name} (ID: {member.id}) na serwerze {member.guild.name}")
    # 1. AKTUALIZACJA LICZNIKÓW I STATYSTYK
    await update_counters(member.guild)
    log_join_activity(member.guild.id)
    
    # 2. POWITANIE
    await send_welcome_message(member.guild, member, 'powitanie')
    
    # 3. AUTOROLE I PRZYWRACANIE RANG
    settings = get_settings(str(member.guild.id))
    
    # A. PRZYWRACANIE RANG (jeśli są w bazie)
    saved_role_ids = get_member_roles(member.guild.id, member.id)
    if saved_role_ids:
        mode = settings.get("autorole_mode", "black")
        restore_cfg = settings.get("autorole_roles", [])
        roles_to_restore = []
        for rid in saved_role_ids:
            role = member.guild.get_role(int(rid))
            if not role: continue
            if mode == "black" and str(rid) not in restore_cfg:
                roles_to_restore.append(role)
            elif mode == "white" and str(rid) in restore_cfg:
                roles_to_restore.append(role)
        if roles_to_restore:
            try:
                await member.add_roles(*roles_to_restore, reason="Przywracanie rang")
                print(f"✅ [AUTOROLE] Przywrócono {len(roles_to_restore)} ról dla {member.name} na {member.guild.name}")
            except Exception as e:
                print(f"❌ [AUTOROLE] Błąd przywracania rang dla {member.name}: {e}")

    # B. AUTOROLE DLA NOWYCH
    auto_roles_to_add = []
    guild_me = member.guild.me
    
    if member.bot:
        bot_roles_cfg = settings.get("autorole_bot_roles", [])
        for rid in bot_roles_cfg:
            try:
                role = member.guild.get_role(int(rid))
                if role:
                    if role < guild_me.top_role:
                        auto_roles_to_add.append(role)
                    else:
                        print(f"⚠️ [AUTOROLE] Rola {role.name} jest wyżej w hierarchii niż bot! Przesuń rolę bota wyżej.")
            except: pass
        if auto_roles_to_add:
            print(f"🤖 [AUTOROLE] Przygotowano {len(auto_roles_to_add)} ról dla bota {member.name}")
    else:
        human_roles_cfg = settings.get("autorole_human_roles", [])
        for rid in human_roles_cfg:
            try:
                role = member.guild.get_role(int(rid))
                if role:
                    if role < guild_me.top_role:
                        auto_roles_to_add.append(role)
                    else:
                        print(f"⚠️ [AUTOROLE] Rola {role.name} jest wyżej w hierarchii niż bot! Przesuń rolę bota wyżej.")
            except: pass
        if auto_roles_to_add:
            print(f"👤 [AUTOROLE] Przygotowano {len(auto_roles_to_add)} ról dla {member.name}")
    
    if auto_roles_to_add:
        try:
            if not guild_me.guild_permissions.manage_roles:
                print(f"❌ [AUTOROLE] Bot NIE MA uprawnienia 'Manage Roles' (Zarządzanie Rolami)!")
            else:
                await member.add_roles(*auto_roles_to_add, reason="AutoRole na start")
                print(f"✅ [AUTOROLE] Nadano role: {[r.name for r in auto_roles_to_add]} dla {member.name}")
        except discord.Forbidden:
            print(f"❌ [AUTOROLE] Brak uprawnień do nadania ról dla {member.name} (Forbidden)")
        except Exception as e:
            print(f"❌ [AUTOROLE] Błąd nadawania ról dla {member.name}: {e}")

@bot.event
async def on_member_remove(member):
    # 1. AKTUALIZACJA LICZNIKÓW
    await update_counters(member.guild)

    # 2. POŻEGNANIE
    await send_welcome_message(member.guild, member, 'pozegnanie')
    
    # 3. ZAPIS RANG PRZED WYJŚCIEM
    roles_to_save = [str(role.id) for role in member.roles if role.name != "@everyone" and not role.managed]
    if roles_to_save:
        save_member_roles(member.guild.id, member.id, roles_to_save)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    if not payload.guild_id: return
    
    # 1. Reaction Roles z Osadzeń (Embeds)
    from database import get_embed_configs
    embed_configs = get_embed_configs(payload.guild_id)
    for cfg in embed_configs:
        if not cfg.get('enabled', 1): continue
        if str(payload.message_id) == str(cfg.get('last_message_id', '')) and str(payload.emoji) == str(cfg.get('reaction_emoji', '')):
            role_id = cfg.get('reaction_role_id')
            if role_id:
                guild = bot.get_guild(payload.guild_id)
                role = guild.get_role(int(role_id))
                member = payload.member or await guild.fetch_member(payload.user_id)
                if role and member:
                    try: await member.add_roles(role, reason="Reaction Role (Osadzenia)")
                    except: pass
                return

    # 2. Reaction Roles z modułu Selfrole
    sr_configs = get_selfrole_configs(payload.guild_id)
    for cfg in sr_configs:
        if not cfg.get('enabled', 1): continue
        if cfg['type'] == 'reaction' and str(payload.message_id) == str(cfg.get('message_id')):
            import json
            try:
                roles = json.loads(cfg['roles_json'])
                for r in roles:
                    if str(payload.emoji) == str(r['emoji']):
                        guild = bot.get_guild(payload.guild_id)
                        role = guild.get_role(int(r['role_id']))
                        member = payload.member or await guild.fetch_member(payload.user_id)
                        if role and member:
                            try: await member.add_roles(role, reason="Selfrole (Reaction)")
                            except: pass
                        break
            except: pass

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id: return
    if not payload.guild_id: return
    
    # 1. Osadzenia
    from database import get_embed_configs
    embed_configs = get_embed_configs(payload.guild_id)
    for cfg in embed_configs:
        if not cfg.get('enabled', 1): continue
        if str(payload.message_id) == str(cfg.get('last_message_id', '')) and str(payload.emoji) == str(cfg.get('reaction_emoji', '')):
            role_id = cfg.get('reaction_role_id')
            if role_id:
                guild = bot.get_guild(payload.guild_id)
                role = guild.get_role(int(role_id))
                member = await guild.fetch_member(payload.user_id)
                if role and member:
                    try: await member.remove_roles(role, reason="Reaction Role (Osadzenia)")
                    except: pass
                return

    # 2. Selfrole
    sr_configs = get_selfrole_configs(payload.guild_id)
    for cfg in sr_configs:
        if not cfg.get('enabled', 1): continue
        if cfg['type'] == 'reaction' and str(payload.message_id) == str(cfg.get('message_id')):
            import json
            try:
                roles = json.loads(cfg['roles_json'])
                for r in roles:
                    if str(payload.emoji) == str(r['emoji']):
                        guild = bot.get_guild(payload.guild_id)
                        role = guild.get_role(int(r['role_id']))
                        member = await guild.fetch_member(payload.user_id)
                        if role and member:
                            try: await member.remove_roles(role, reason="Selfrole (Reaction)")
                            except: pass
                        break
            except: pass

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    settings = get_settings(str(message.guild.id))
    
    # --- ANTY-LINK SYSTEM ---
    if settings.get("automod_antilink"):
        import re
        url_pattern = r'(https?://\S+|discord\.gg/\S+|discord\.com/invite/\S+)'
        links = re.findall(url_pattern, message.content)
        
        if links:
            # Pomiń administratorów
            if not message.author.guild_permissions.administrator:
                view = LinkReviewView(message)
                embed = discord.Embed(
                    title="🔍 Wykryto Link",
                    description=f"Użytkownik {message.author.mention} wysłał link, który wymaga weryfikacji.\n\n**Treść:**\n{message.content}",
                    color=0xffaa00
                )
                embed.set_footer(text="Moderatorzy mogą zatwierdzić lub usunąć tę wiadomość.")
                await message.channel.send(embed=embed, view=view)

    # --- ANTY-PHISHING SYSTEM ---
    if settings.get("automod_antiphishing"):
        # Wzorce typowe dla nitro scamów i phishingu
        phishing_patterns = [
            r'discord(?:-app)?-nitro', r'discord(?:-app)?-gift', r'dlscord', 
            r'nitro-discord', r'free-nitro', r'steam-nitro', r'nitro-gift',
            r'discord(?:-app)?\.net', r'discord(?:-app)?\.org', r'nitro\.gl'
        ]
        is_phishing = False
        content_lower = message.content.lower()
        
        for pattern in phishing_patterns:
            if re.search(pattern, content_lower):
                # Jeśli wzorzec pasuje, ale domena NIE jest oficjalna
                official_domains = ['discord.com', 'discord.gift', 'discordapp.com', 'discord.gg']
                if not any(dom in content_lower for dom in official_domains):
                    is_phishing = True
                    break
        
        if is_phishing:
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()
                    ph_embed = discord.Embed(
                        title="🛡️ System Anty-Phishing",
                        description=f"⚠️ {message.author.mention}, Twoja wiadomość została zablokowana!\n\n**Powód:** Wykryto podejrzany link mogący służyć do wyłudzania danych (Phishing/Nitro Scam).",
                        color=0xff0000
                    )
                    ph_embed.set_footer(text="Polski Bot • Bezpieczeństwo")
                    await message.channel.send(embed=ph_embed, delete_after=15)
                    return
                except: pass

    # Logowanie aktywności i przetwarzanie komend
    if message.guild:
        log_message_activity(message.guild.id, message.channel.id)
    
    await bot.process_commands(message)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    # Obsługa Button Roles i Select Roles
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get('custom_id', '')
    
    # Obsługa przycisków
    if custom_id.startswith("selfrole_btn_"):
        role_id = int(custom_id.replace("selfrole_btn_", ""))
        
        # SPRAWDZANIE CZY MODUŁ JEST WŁĄCZONY (Przynajmniej jedna aktywna konf. z tą rolą)
        sr_configs = get_selfrole_configs(interaction.guild.id)
        is_active = False
        for cfg in sr_configs:
            if not cfg.get('enabled', 1): continue
            try:
                roles = json.loads(cfg.get('roles_json', '[]'))
                if any(str(r.get('role_id')) == str(role_id) for r in roles):
                    is_active = True; break
            except: pass
        
        if not is_active:
            return await interaction.response.send_message("⚠️ Ten panel jest obecnie wyłączony.", ephemeral=True)

        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.send_message("❌ Nie znaleziono roli!", ephemeral=True)
            
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Odebrano rolę **{role.name}**.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Nadano rolę **{role.name}**.", ephemeral=True)

    # Obsługa menu wyboru (Select Menu)
    elif custom_id.startswith("selfrole_sel_"):
        selected_role_id = int(interaction.data.get('values', [0])[0])
        
        # SPRAWDZANIE CZY MODUŁ JEST WŁĄCZONY
        sr_configs = get_selfrole_configs(interaction.guild.id)
        is_active = False
        for cfg in sr_configs:
            if not cfg.get('enabled', 1): continue
            try:
                roles = json.loads(cfg.get('roles_json', '[]'))
                if any(str(r.get('role_id')) == str(selected_role_id) for r in roles):
                    is_active = True; break
            except: pass
            
        if not is_active:
            return await interaction.response.send_message("⚠️ Ten panel jest obecnie wyłączony.", ephemeral=True)

        role = interaction.guild.get_role(selected_role_id)
        if not role:
            return await interaction.response.send_message("❌ Nie znaleziono roli!", ephemeral=True)
            
        # Logika: daj wybraną, zabierz inne z tego samego menu? 
        # Na razie: po prostu przełącz (toggle)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Odebrano rolę **{role.name}**.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Nadano rolę **{role.name}**.", ephemeral=True)

@bot.event
async def on_voice_state_update(member, before, after):
    # 1. Obsługa Connect Role (Selfrole)
    if before.channel != after.channel:
        configs = get_selfrole_configs(member.guild.id)
        voice_configs = [c for c in configs if c['type'] == 'voice']
        
        for cfg in voice_configs:
            if not cfg.get('enabled', 1): continue
            role_id = cfg.get('role_id')
            if not role_id: continue
            role = member.guild.get_role(int(role_id))
            if not role: continue
            
            if after.channel and not before.channel:
                try: await member.add_roles(role, reason="Connect Role")
                except: pass
            elif not after.channel and before.channel:
                try: await member.remove_roles(role, reason="Connect Role")
                except: pass

    # 2. Obsługa Logów Voice
    if before.channel != after.channel:
        embed = discord.Embed(color=get_embed_color(member.guild), timestamp=datetime.datetime.now())
        embed.set_author(name=f"{member.display_name} - Voice", icon_url=member.display_avatar.url)
        if before.channel is None:
            embed.title = "🎙️ Połączono z Voice"
            embed.description = f"Użytkownik dołączył do {after.channel.mention}"
        elif after.channel is None:
            embed.title = "🔇 Rozłączono z Voice"
            embed.description = f"Użytkownik opuścił {before.channel.mention}"
        else:
            embed.title = "🔄 Zmiana kanału Voice"
            embed.description = f"Przeniesiono z {before.channel.mention} do {after.channel.mention}"
        await send_log(member.guild, "voice_activity", embed)



@bot.event
async def on_ready():
    # Rejestracja stałych widoków (Persistent Views)
    bot.add_view(TicketActions())
    
    # Synchronizacja komend slash
    try:
        await bot.tree.sync()
        print(f"[OK] Zalogowano jako {bot.user} i zsynchronizowano slash commands.")
    except Exception as e:
        print(f"[OK] Zalogowano jako {bot.user} (Slash sync error: {e})")
    
    # Uruchomienie zadań w tle (pętle)
    if not check_media_streams.is_running():
        check_media_streams.start()
    
    if not update_counters_loop.is_running():
        update_counters_loop.start()

    if not update_status_file.is_running():
        update_status_file.start()


# --- SYSTEM POWIADOMIEŃ O MEDIACH (YOUTUBE, TWITCH, TIKTOK, KICK) ---
from discord.ext import tasks
import aiohttp

# Pamięć bota, żeby nie wysyłał powiadomienia co 5 minut podczas jednego streama
live_status_memory = {}

@tasks.loop(minutes=5)
async def check_media_streams():
    """Pętla w tle sprawdzająca statusy kanałów na YouTube, Twitch, Kick i TikTok."""
    print("📡 [RADAR] Rozpoczynam skanowanie platform (Twitch, YouTube, Kick, TikTok)...")
    
    # Odczyt kluczy z .env
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
    TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
    TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
    
    # Autoryzacja Twitcha
    twitch_token = None
    if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        twitch_token = data.get('access_token')
        except Exception as e:
            print(f"⚠️ [TWITCH] Błąd autoryzacji: {e}")

    # Przeglądamy wszystkie serwery, na których jest bot
    for guild in bot.guilds:
        # Pobieramy konfiguracje z bazy danych dla danego serwera
        configs = get_media_configs(guild.id)
        if not configs:
            continue
            
        for cfg in configs:
            if not cfg.get('enabled') or not cfg.get('account_id') or not cfg.get('discord_channel_id'):
                continue
                
            platform = cfg['platform'].lower()
            raw_account = cfg['account_id'].strip()
            
            # --- INTELIGENTNY FILTR URL ---
            # Jeśli użytkownik wkleił pełny link, wyciągamy samą nazwę użytkownika lub ID
            if "twitch.tv/" in raw_account:
                raw_account = raw_account.split("twitch.tv/")[-1].split("?")[0].strip("/")
            elif "kick.com/" in raw_account:
                raw_account = raw_account.split("kick.com/")[-1].split("?")[0].strip("/")
            elif "tiktok.com/" in raw_account:
                raw_account = raw_account.split("tiktok.com/")[-1].split("?")[0].strip("/")
            elif "youtube.com/" in raw_account or "youtu.be/" in raw_account:
                if "/@" in raw_account:
                    raw_account = raw_account.split("/@")[-1].split("?")[0].split("/")[0]
                elif "/c/" in raw_account:
                    raw_account = raw_account.split("/c/")[-1].split("?")[0].split("/")[0]
                elif "/channel/" in raw_account:
                    raw_account = raw_account.split("/channel/")[-1].split("?")[0].split("/")[0]
                else:
                    raw_account = raw_account.split("/")[-1].split("?")[0].strip("/")
            
            # Bezpieczne usunięcie `@` (np. uzytkownik wpisał samo @nazwa)
            account = raw_account.replace('@', '')
            
            channel_id = int(cfg['discord_channel_id'])
            memory_key = f"{guild.id}_{platform}_{account}"
            
            is_live = False
            stream_url = ""
            stream_title = ""
            stream_thumb = ""
            
            try:
                async with aiohttp.ClientSession() as session:
                    # ========================================
                    # LOGIKA DLA KICK
                    # ========================================
                    if platform == "kick":
                        async with session.get(f"https://kick.com/api/v1/channels/{account}") as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get('livestream') is not None:
                                    is_live = True
                                    stream_url = f"https://kick.com/{account}"
                                    stream_title = data['livestream'].get('session_title', f"Transmisja Kick")
                                    stream_thumb = data['livestream'].get('thumbnail', {}).get('url', '')

                    # ========================================
                    # LOGIKA DLA TWITCH
                    # ========================================
                    elif platform == "twitch" and twitch_token:
                        headers = {
                            "Client-ID": TWITCH_CLIENT_ID,
                            "Authorization": f"Bearer {twitch_token}"
                        }
                        async with session.get(f"https://api.twitch.tv/helix/streams?user_login={account}", headers=headers) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get('data') and len(data['data']) > 0:
                                    stream_data = data['data'][0]
                                    is_live = True
                                    stream_url = f"https://twitch.tv/{account}"
                                    stream_title = stream_data.get('title', "Transmisja Twitch")
                                    stream_thumb = stream_data.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
                                    
                    # ========================================
                    # LOGIKA DLA YOUTUBE (Ostatni film lub Live)
                    # ========================================
                    elif platform == "youtube" and YOUTUBE_API_KEY:
                        # Wyszukiwanie kanału po nazwie, by zdobyć ID
                        async with session.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={account}&key={YOUTUBE_API_KEY}") as ch_resp:
                            if ch_resp.status == 200:
                                ch_data = await ch_resp.json()
                                if ch_data.get('items') and len(ch_data['items']) > 0:
                                    yt_channel_id = ch_data['items'][0]['id']['channelId']
                                    # Pobranie najnowszego materiału
                                    async with session.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={yt_channel_id}&maxResults=1&order=date&type=video&key={YOUTUBE_API_KEY}") as vid_resp:
                                        if vid_resp.status == 200:
                                            vid_data = await vid_resp.json()
                                            if vid_data.get('items') and len(vid_data['items']) > 0:
                                                video = vid_data['items'][0]
                                                vid_id = video['id']['videoId']
                                                # Weryfikacja czy tego filmu już nie powiadamialiśmy (traktujemy wideo ID jako status)
                                                if live_status_memory.get(memory_key) != vid_id:
                                                    is_live = True
                                                    stream_url = f"https://youtube.com/watch?v={vid_id}"
                                                    stream_title = video['snippet']['title']
                                                    stream_thumb = video['snippet']['thumbnails']['high']['url']
                                                    live_status_memory[memory_key] = vid_id # Zapisz ten konkretny film!
                    
                    # ========================================
                    # LOGIKA DLA TIKTOK (Uproszczona zewn. / brak pełnego API)
                    # ========================================
                    elif platform == "tiktok":
                        # UWAGA: TikTok oficjalnie blokuje scrape'owanie. To jest bardzo podstawowy sprawdzian.
                        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                        async with session.get(f"https://www.tiktok.com/@{account}/live", headers=headers) as resp:
                            # Jeżeli strona live istnieje i nie ma redirektu, być może użytkownik jest live
                            # To tylko uproszczona atrapa. Prawdziwe API TikToka jest hermetyczne.
                            if resp.status == 200 and "room_id" in await resp.text():
                                is_live = True
                                stream_url = f"https://www.tiktok.com/@{account}/live"
                                stream_title = f"{account} właśnie transmituje na TikTok!"

            except Exception as e:
                print(f"⚠️ [RADAR] Błąd odczytu dla {account} na {platform}: {e}")

            # Wysyłanie powiadomienia na Discordzie
            was_live_recently = (live_status_memory.get(memory_key) == True)
            
            # YouTube ma specjalną logikę zapisywania ID filmu, reszta ma True/False
            if platform != "youtube":
                if is_live and not was_live_recently:
                    # Ktoś zaczął stream!
                    live_status_memory[memory_key] = True
                    await _send_media_notification(guild, channel_id, cfg, stream_title, stream_url, stream_thumb, account, platform)
                elif not is_live and was_live_recently:
                    # Ktoś skończył stream
                    live_status_memory[memory_key] = False
            elif platform == "youtube" and is_live:
                # Wysłanie powiadomienia YouTube o NOWYM filmie
                await _send_media_notification(guild, channel_id, cfg, stream_title, stream_url, stream_thumb, account, platform)

async def _send_media_notification(guild, channel_id, cfg, stream_title, stream_url, stream_thumb, account, platform):
    """Wewnętrzna funkcja do wysłania ładnego powiadomienia"""
    try:
        channel = guild.get_channel(channel_id)
        if not channel: return
        
        # Wiadomość ustawiona przez użytkownika z obsługą zmiennych
        message_text = cfg['message'].replace('{account}', f"**{account}**")
        
        # Kolory w zależności od platformy (używamy jako fallback, jeśli nie ustawiono customowego)
        platform_colors = {
            "youtube": 0xFF0000,
            "twitch": 0x9146FF,
            "kick": 0x53FC18,
            "tiktok": 0x000000
        }
        
        # Używamy koloru bota jako głównego
        embed_color = get_embed_color(guild)
        
        embed = discord.Embed(
            title=f"🔴 {stream_title}",
            url=stream_url,
            color=embed_color
        )
        if stream_thumb:
            embed.set_image(url=stream_thumb)
            
        embed.set_footer(text=f"Powiadomienie: {platform.upper()}", icon_url=guild.icon.url if guild.icon else None)
        
        await channel.send(content=message_text, embed=embed)
    except Exception as e:
        print(f"❌ [RADAR] Nie udało się wysłać powiadomienia na kanał {channel_id}: {e}")

# --- SYSTEM LOGÓW (LOGI SERWEROWE) ---
async def send_log(guild, category, embed):
    """Pomocnicza funkcja do wysyłania logów na wybrany kanał i do bazy danych."""
    try:
        from database import get_settings, add_audit_log
        settings = get_settings(str(guild.id))
        
        # 1. Zapis do bazy danych (Zawsze, dla zakładki Zmiany na serwerze)
        user_info = "System"
        user_id = "0"
        action = embed.title if embed.title else "Akcja"
        details = ""
        for field in embed.fields:
            details += f"{field.name}: {field.value}\n"
        if embed.description:
            details += f"Opis: {embed.description}\n"
            
        # Próbujemy wyciągnąć autora z pól jeśli tam jest
        for field in embed.fields:
            if "Autor" in field.name or "Użytkownik" in field.name:
                user_info = field.value
        
        add_audit_log(guild.id, category, user_info, user_id, action, details.strip())

        # 2. Wysyłka na kanał Discord (Tylko jeśli włączone)
        channel_id = settings.get('logs_channel_id')
        if not channel_id: return
        
        enabled_key = f"logs_{category}"
        if not settings.get(enabled_key, False): return
        
        channel = guild.get_channel(int(channel_id))
        if channel:
            # Ustawiamy globalny kolor dla logów
            embed.color = get_embed_color(guild)
            await channel.send(embed=embed)

    except Exception as e:
        print(f"❌ [LOGS] Błąd logowania ({category}): {e}")

@bot.event
async def on_message_delete(message):
    if not message.guild or message.author.bot: return
    embed = discord.Embed(title="🗑️ Usunięto wiadomość", color=get_embed_color(message.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Autor", value=f"{message.author} ({message.author.id})")
    embed.add_field(name="Kanał", value=message.channel.mention)
    embed.add_field(name="Treść", value=message.content[:1024] or "*Brak treści (np. załącznik)*", inline=False)
    await send_log(message.guild, "msg_updates", embed)

@bot.event
async def on_message_edit(before, after):
    if not before.guild or before.author.bot or before.content == after.content: return
    embed = discord.Embed(title="📝 Edytowano wiadomość", color=get_embed_color(before.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Autor", value=f"{before.author} ({before.author.id})")
    embed.add_field(name="Kanał", value=before.channel.mention)
    embed.add_field(name="Przed", value=before.content[:1024] or "*Puste*", inline=False)
    embed.add_field(name="Po", value=after.content[:1024] or "*Puste*", inline=False)
    await send_log(before.guild, "msg_updates", embed)

@bot.event
async def on_member_join(member):
    embed = discord.Embed(title="📥 Użytkownik dołączył", color=get_embed_color(member.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Użytkownik", value=f"{member} ({member.id})")
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, "join_leave", embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(title="📤 Użytkownik opuścił serwer", color=get_embed_color(member.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Użytkownik", value=f"{member} ({member.id})")
    await send_log(member.guild, "join_leave", embed)

@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Zbanowano użytkownika", color=get_embed_color(guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Użytkownik", value=f"{user} ({user.id})")
    await send_log(guild, "mod_actions", embed)

@bot.event
async def on_member_unban(guild, user):
    embed = discord.Embed(title="✅ Odbanowano użytkownika", color=get_embed_color(guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Użytkownik", value=f"{user} ({user.id})")
    await send_log(guild, "mod_actions", embed)

@bot.event
async def on_member_update(before, after):
    # Role updates
    if before.roles != after.roles:
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        if added or removed:
            embed = discord.Embed(title="🛡️ Zmiana ról użytkownika", color=get_embed_color(before.guild), timestamp=datetime.datetime.now())
            embed.add_field(name="Użytkownik", value=f"{after} ({after.id})")
            if added: embed.add_field(name="Nadano", value=", ".join(added), inline=False)
            if removed: embed.add_field(name="Odebrano", value=", ".join(removed), inline=False)
            await send_log(after.guild, "role_updates", embed)

@bot.event
async def on_guild_channel_create(channel):
    embed = discord.Embed(title="📂 Stworzono kanał", color=get_embed_color(channel.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Nazwa", value=f"#{channel.name} ({channel.id})")
    embed.add_field(name="Typ", value=str(channel.type))
    await send_log(channel.guild, "guild_updates", embed)

@bot.event
async def on_guild_channel_delete(channel):
    embed = discord.Embed(title="🗑️ Usunięto kanał", color=get_embed_color(channel.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Nazwa", value=f"#{channel.name} ({channel.id})")
    await send_log(channel.guild, "guild_updates", embed)


@bot.event
async def on_guild_role_create(role):
    embed = discord.Embed(title="🛡️ Stworzono nową rolę", color=get_embed_color(role.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Nazwa", value=f"{role.name} ({role.id})")
    await send_log(role.guild, "guild_updates", embed)

@bot.event
async def on_guild_role_delete(role):
    embed = discord.Embed(title="🗑️ Usunięto rolę", color=get_embed_color(role.guild), timestamp=datetime.datetime.now())
    embed.add_field(name="Nazwa", value=f"{role.name} ({role.id})")
    await send_log(role.guild, "guild_updates", embed)

# --- STATUS BOTA DO PLIKU I SYNCHRONIZACJA (Dla stabilności na PythonAnywhere) ---
@tasks.loop(seconds=5) # Częstsze sprawdzanie dla lepszej responsywności
async def update_status_file():
    try:
        import json
        import time
        import os
        import glob
        
        # 1. Zapis statusu
        status = {
            "latency": round(bot.latency * 1000) if bot.latency else 0,
            "last_seen": time.time(),
            "status": "online"
        }
        with open(STATUS_FILE_PATH, "w") as f:
            json.dump(status, f)
            
        # 2. Sprawdzanie czy są oczekujące synchronizacje (POST z dashboardu)
        sync_files = glob.glob("sync_needed_*.json")
        for sf in sync_files:
            try:
                with open(sf, "r") as f:
                    data = json.load(f)
                
                guild_id = sf.replace("sync_needed_", "").replace(".json", "")
                guild = bot.get_guild(int(guild_id))
                
                if guild:
                    endpoint = data.get('endpoint', '')
                    payload = data.get('data', {})

                    if "sync_counters" in endpoint:
                        await update_counters(guild)
                    elif "sync_boosters" in endpoint:
                        await sync_booster_roles(guild)
                    elif "send_embed" in endpoint:
                        # Emulacja handle_send_embed
                        config_id = payload.get('config_id')
                        from database import get_embed_configs
                        configs = get_embed_configs(guild_id)
                        cfg = next((c for c in configs if c['id'] == config_id), None)
                        if cfg:
                            channel = guild.get_channel(int(cfg['channel_id']))
                            if channel:
                                # Dynamiczny kolor
                                custom_color = cfg.get('color')
                                embed_color = int(custom_color.replace('#', ''), 16) if custom_color and custom_color.strip() else get_embed_color(guild)
                                emb = discord.Embed(title=cfg.get('title', ''), description=cfg.get('description', ''), color=embed_color)
                                if cfg.get('footer'): emb.set_footer(text=cfg['footer'])
                                if cfg.get('image_url'): emb.set_image(url=cfg['image_url'])
                                if cfg.get('thumbnail_url'): emb.set_thumbnail(url=cfg['thumbnail_url'])
                                if cfg.get('author'): emb.set_author(name=cfg['author'], icon_url=cfg.get('author_url'))
                                await channel.send(embed=emb)
                    elif "send_selfrole" in endpoint:
                        # Emulacja handle_send_selfrole
                        config_id = payload.get('config_id')
                        from database import get_selfrole_configs
                        configs = get_selfrole_configs(guild_id)
                        cfg = next((c for c in configs if str(c['id']) == str(config_id)), None)
                        if cfg:
                            channel = guild.get_channel(int(cfg['channel_id']))
                            if channel:
                                await send_selfrole_panel(channel, cfg) # Potrzebujemy tej funkcji pomocniczej
                    elif "test_welcome" in endpoint:
                        # Emulacja handle_test_welcome
                        config_id = payload.get('config_id')
                        type = payload.get('type')
                        member = guild.members[0] if guild.members else bot.user
                        await send_welcome_message(guild, member, type, target_id=config_id)
                        
                os.remove(sf) # Usuwamy plik po obsłużeniu
            except Exception as e:
                print(f"[SYNC ERROR] {sf}: {e}")
                if os.path.exists(sf): os.remove(sf)
    except: pass


@tasks.loop(minutes=10)
async def update_counters_loop():
    """Okresowa aktualizacja wszystkich liczników na serwerach."""
    for guild in bot.guilds:
        try:
            await update_counters(guild)
        except:
            pass
from aiohttp import web

async def handle_latency(request):
    return web.json_response({'latency': round(bot.latency * 1000)})

async def handle_guild_channels(request):
    guild_id = request.match_info.get('guild_id')
    guild = bot.get_guild(int(guild_id))
    if not guild: return web.json_response([], status=404)
    channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    return web.json_response(channels)

async def handle_guild_roles(request):
    guild_id = request.match_info.get('guild_id')
    guild = bot.get_guild(int(guild_id))
    if not guild: return web.json_response([], status=404)
    roles = []
    for r in guild.roles:
        if r.name != "@everyone" and not r.managed:
            color = str(r.color) if str(r.color) != "#000000" else "#b5bac1"
            roles.append({"id": str(r.id), "name": r.name, "color": color})
    return web.json_response(roles)

async def handle_test_welcome(request):
    data = await request.json()
    guild_id = data.get('guild_id')
    config_id = data.get('config_id')
    type = data.get('type')
    
    guild = bot.get_guild(int(guild_id))
    if not guild: return web.json_response({'success': False, 'error': 'Bot nie jest na serwerze'}, status=404)
    
    member = guild.members[0] if guild.members else bot.user
    await send_welcome_message(guild, member, type, target_id=config_id)
    return web.json_response({'success': True})

async def handle_sync_counters(request):
    guild_id = request.match_info.get('guild_id')
    guild = bot.get_guild(int(guild_id))
    if guild:
        await update_counters(guild)
        return web.json_response({'success': True})
    return web.json_response({'success': False}, status=404)

async def handle_sync_boosters(request):
    guild_id = request.match_info.get('guild_id')
    guild = bot.get_guild(int(guild_id))
    if guild:
        asyncio.create_task(sync_booster_roles(guild))
        return web.json_response({'success': True})
    return web.json_response({'success': False}, status=404)

async def handle_send_embed(request):
    data = await request.json()
    guild_id = data.get('guild_id')
    config_id = data.get('config_id')
    
    from database import get_embed_configs, DB_NAME
    import sqlite3
    configs = get_embed_configs(guild_id)
    cfg = next((c for c in configs if str(c['id']) == str(config_id)), None)
    if not cfg: return web.json_response({'success': False, 'error': 'Nie znaleziono configu'}, status=404)
    
    guild = bot.get_guild(int(guild_id))
    if not guild: return web.json_response({'success': False, 'error': 'Bot poza serwerem'}, status=404)
    
    channel = guild.get_channel(int(cfg['channel_id']))
    if not channel: return web.json_response({'success': False, 'error': 'Brak kanału'}, status=404)

    import discord
    
    # Kolorystyka
    custom_color = cfg.get('color')
    if custom_color and custom_color.strip():
        try:
            embed_color = int(custom_color.replace('#', ''), 16)
        except:
            embed_color = get_embed_color(guild)
    else:
        embed_color = get_embed_color(guild)

    # Budowanie listy EmbedĂłw
    embeds = []
    
    if cfg.get('category') == 'rules':
        try:
            # PrĂłbujemy sparsowaÄ‡ bloki zasad
            blocks = json.loads(cfg.get('description', '[]'))
            if isinstance(blocks, list) and len(blocks) > 0:
                for i, block in enumerate(blocks):
                    eb = discord.Embed(description=block.get('text', ''), color=embed_color)
                    if i == 0:
                        eb.title = cfg.get('name', 'Regulamin')
                        if cfg.get('author'): eb.set_author(name=cfg['author'], url=cfg.get('author_url'))
                    if block.get('image'):
                        eb.set_image(url=block['image'])
                    if i == len(blocks) - 1:
                        if cfg.get('footer'): eb.set_footer(text=cfg['footer'])
                        if cfg.get('timestamp'): eb.timestamp = datetime.datetime.now()
                    embeds.append(eb)
            else:
                # Fallback jeĹ›li JSON jest pusty lub nie jest listÄ…
                e = discord.Embed(title=cfg.get('name', 'Regulamin'), description=cfg.get('description', ''), color=embed_color)
                embeds.append(e)
        except:
            # Fallback jeĹ›li to nie JSON
            e = discord.Embed(title=cfg.get('name', 'Regulamin'), description=cfg.get('description', ''), color=embed_color)
            embeds.append(e)
    else:
        # Standardowy embed
        e = discord.Embed(title=cfg.get('title', ''), description=cfg.get('description', ''), color=embed_color)
        if cfg.get('footer'): e.set_footer(text=cfg['footer'])
        if cfg.get('image_url'): e.set_image(url=cfg['image_url'])
        if cfg.get('thumbnail_url'): e.set_thumbnail(url=cfg['thumbnail_url'])
        if cfg.get('author'): e.set_author(name=cfg['author'], url=cfg.get('author_url'))
        if cfg.get('title_url'): e.url = cfg['title_url']
        if cfg.get('timestamp'): e.timestamp = datetime.datetime.now()
        embeds.append(e)

    msg = None
    last_msg_id = cfg.get('last_message_id')
    
    if last_msg_id:
        try:
            old_msg = await channel.fetch_message(int(last_msg_id))
            await old_msg.edit(embeds=embeds)
            msg = old_msg
        except: pass

    if not msg:
        msg = await channel.send(embeds=embeds)
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.cursor().execute("UPDATE embed_configs SET last_message_id = ? WHERE id = ?", (str(msg.id), config_id))
            conn.commit()
            conn.close()
        except: pass
        
    if cfg.get('category') == 'rules' and cfg.get('reaction_emoji'):
        try: await msg.add_reaction(cfg['reaction_emoji'])
        except: pass

    return web.json_response({'success': True})

async def send_selfrole_panel(channel, cfg):
    import json
    import discord
    from discord import ui
    
    # Budowanie Embedu
    emb = discord.Embed(
        title=cfg.get('name', 'Panel RĂłl'), 
        description=cfg.get('description', ''), 
        color=get_embed_color(channel.guild)
    )
    if cfg.get('thumbnail_url'):
        emb.set_thumbnail(url=cfg['thumbnail_url'])
    if cfg.get('image_url'):
        emb.set_image(url=cfg['image_url'])
    
    roles_data = json.loads(cfg.get('roles_json', '[]'))
    msg = None
    existing_msg_id = cfg.get('message_id')
    
    # PrĂłba edycji istniejÄ…cej wiadomoĹ›ci
    if existing_msg_id:
        try:
            msg = await channel.fetch_message(int(existing_msg_id))
        except: pass

    if cfg['type'] == 'reaction':
        if msg:
            await msg.edit(embed=emb)
        else:
            msg = await channel.send(embed=emb)
            # Zapisujemy message_id w bazie
            from database import DB_NAME
            import sqlite3
            try:
                conn = sqlite3.connect(DB_NAME)
                conn.cursor().execute("UPDATE self_role_configs SET message_id = ? WHERE id = ?", (str(msg.id), cfg['id']))
                conn.commit()
                conn.close()
            except: pass
        
        # Aktualizacja reakcji
        for r in roles_data:
            try: await msg.add_reaction(r['emoji'])
            except: pass
            
    elif cfg['type'] == 'button':
        class RoleView(ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                for r in roles_data:
                    btn = ui.Button(
                        label=r.get('label', 'Rola'), 
                        emoji=r.get('emoji'), 
                        custom_id=f"selfrole_btn_{r['role_id']}",
                        style=discord.ButtonStyle.secondary
                    )
                    self.add_item(btn)
        
        if msg:
            await msg.edit(embed=emb, view=RoleView())
        else:
            msg = await channel.send(embed=emb, view=RoleView())
            from database import DB_NAME
            import sqlite3
            try:
                conn = sqlite3.connect(DB_NAME)
                conn.cursor().execute("UPDATE self_role_configs SET message_id = ? WHERE id = ?", (str(msg.id), cfg['id']))
                conn.commit()
                conn.close()
            except: pass

async def handle_send_selfrole(request):
    data = await request.json()
    guild_id = data.get('guild_id')
    config_id = data.get('config_id')
    
    from database import get_selfrole_configs
    configs = get_selfrole_configs(guild_id)
    cfg = next((c for c in configs if str(c['id']) == str(config_id)), None)
    if not cfg: return web.json_response({'success': False, 'error': 'Nie znaleziono configu'}, status=404)
    
    guild = bot.get_guild(int(guild_id))
    if not guild: return web.json_response({'success': False, 'error': 'Bot poza serwerem'}, status=404)
    
    channel = guild.get_channel(int(cfg['channel_id']))
    if not channel: return web.json_response({'success': False, 'error': 'Brak kanału'}, status=404)

    await send_selfrole_panel(channel, cfg)
    return web.json_response({'success': True})
        
    return web.json_response({'success': True})

async def run_internal_api():
    # Próba zwolnienia portu 5006 przed startem (tylko lokalnie)
    if sys.platform == 'win32':
        try:
            import os
            # Zabijamy procesy na porcie 5006, aby uniknąć [Errno 10048]
            os.system('for /f "tokens=5" %a in (\'netstat -aon ^| findstr :5006\') do taskkill /f /pid %a')
        except: pass

    app = web.Application()
    app.add_routes([
        web.get('/latency', handle_latency),
        web.get('/guilds/{guild_id}/channels', handle_guild_channels),
        web.get('/guilds/{guild_id}/roles', handle_guild_roles),
        web.post('/test_welcome', handle_test_welcome),
        web.post('/guilds/{guild_id}/sync_counters', handle_sync_counters),
        web.post('/guilds/{guild_id}/sync_boosters', handle_sync_boosters),
        web.post('/send_embed', handle_send_embed),
        web.post('/send_selfrole', handle_send_selfrole),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, '127.0.0.1', 5006) # Wewnętrzny port komunikacji
        await site.start()
        print("[API] Wewnętrzny serwer komunikacji bota działa na porcie 5006")
    except Exception as e:
        print(f"[API] Błąd uruchamiania serwera komunikacji na porcie 5006: {e}")


def update_emergency_status(msg):
    """Zapisuje krytyczny bĹ‚Ä…d do pliku statusu, aby dashboard mĂłgĹ‚ go wyĹ›wietliÄ‡."""
    try:
        import json
        import time
        status = {
            "latency": 0,
            "last_seen": time.time(),
            "status": "error",
            "error_msg": msg
        }
        with open(STATUS_FILE_PATH, "w") as f:
            json.dump(status, f)
    except: pass


async def run_bot():
    if not TOKEN: 
        print("[!] Brak tokena w .env")
        update_emergency_status("Brak tokena DISCORD_BOT_TOKEN w pliku .env")
        return
    
    # Uruchamiamy API w tle
    asyncio.create_task(run_internal_api())
    
    try:
        print("[SYSTEM] PrĂłba poĹ‚Ä…czenia z Discordem...")
        await bot.start(TOKEN)
    except discord.LoginFailure:
        msg = "BĹ Ă„D LOGOWANIA: NieprawidĹ‚owy token bota!"
        print(f"[!] {msg}")
        update_emergency_status(msg)
    except discord.PrivilegedIntentsRequired:
        msg = "BĹ Ă„D INTENCJI: Musisz wĹ‚Ä…czyÄ‡ 'Server Members Intent' oraz 'Message Content Intent' w Discord Developer Portal!"
        print("\n" + "="*50)
        print(f" [!] {msg}")
        print("="*50 + "\n")
        update_emergency_status(msg)
        
        # W trybie awaryjnym czekamy, aby proces nie padĹ‚ i API dziaĹ‚aĹ‚o
        while True:
            await asyncio.sleep(30)
            update_emergency_status(msg)
    except Exception as e:
        msg = f"BĹ Ă„D KRYTYCZNY: {e}"
        print(f"[!] {msg}")
        update_emergency_status(msg)

if __name__ == "__main__":
    import sys
    # Ustawienie kodowania dla Windows, aby uniknąć UnicodeEncodeError
    if sys.platform == 'win32':
        import io
        try: sys.stdout.reconfigure(encoding='utf-8')
        except: pass
        try: sys.stderr.reconfigure(encoding='utf-8')
        except: pass

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass