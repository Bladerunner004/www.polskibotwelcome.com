import discord
from discord.ext import commands
import asyncio
import yt_dlp
from database import get_settings, is_command_enabled

# Konfiguracja yt_dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0', # bindowanie do IPv4
    'extractor_args': {
        'youtube': {
            'player_client': 'ios,android,web_embedded'
        }
    }
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # Pobieramy pierwszy wynik wyszukiwania/playlisty
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

def get_music_settings(ctx):
    if getattr(ctx.bot, 'IS_MUSIC_BOT', False):
        from database import get_music_bot_by_id
        m_bot = get_music_bot_by_id(ctx.bot.MUSIC_BOT_ID)
        if m_bot:
            return {
                "music_enabled": m_bot.get("music_enabled", True),
                "music_volume": m_bot.get("music_volume", 100),
                "music_dj_role_id": m_bot.get("music_dj_role_id"),
                "music_247": m_bot.get("music_247", False),
                "music_high_quality": m_bot.get("music_high_quality", False),
                "commands_channel_id": m_bot.get("commands_channel_id")
            }
    return get_settings(str(ctx.guild.id))

def check_music_enabled():
    async def predicate(ctx):
        if not ctx.guild:
            return False
        
        # 1. Sprawdzamy czy cały moduł muzyczny jest włączony na serwerze
        settings = get_music_settings(ctx)
        if not settings.get("music_enabled", True):
            await ctx.send("❌ Moduł muzyczny jest wyłączony na tym serwerze! Włącz go w panelu WWW.", ephemeral=True)
            return False
            
        # 2. Sprawdzamy czy konkretna komenda nie została wyłączona
        if not is_command_enabled(ctx.guild.id, ctx.command.name):
            await ctx.send(f"❌ Komenda `/{ctx.command.name}` jest wyłączona na tym serwerze!", ephemeral=True)
            return False
            
        # 3. Jeśli jest rola DJ, sprawdzamy uprawnienia dla komend sterujących
        dj_commands = ["skip", "stop", "volume", "shuffle", "pause", "resume"]
        if ctx.command.name in dj_commands:
            dj_role_id = settings.get("music_dj_role_id")
            if dj_role_id and str(dj_role_id).isdigit():
                dj_role = ctx.guild.get_role(int(dj_role_id))
                if dj_role and dj_role not in ctx.author.roles and not ctx.author.guild_permissions.manage_guild:
                    await ctx.send(f"❌ Ta komenda wymaga posiadania roli DJ: {dj_role.mention}!", ephemeral=True)
                    return False
                    
        return True
    return commands.check(predicate)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Kolejki odtwarzania per serwer: guild_id -> list of dicts
        self.queues = {}
        # Aktualnie odtwarzany utwór: guild_id -> dict
        self.current_tracks = {}
        # Status pauzy: guild_id -> bool
        self.paused = {}

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    def format_duration(self, seconds):
        if not seconds:
            return "N/A"
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"

    def play_next(self, ctx):
        asyncio.run_coroutine_threadsafe(self.play_next_async(ctx), self.bot.loop)

    async def play_next_async(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        voice_client = ctx.guild.voice_client

        if not voice_client or not voice_client.is_connected():
            self.current_tracks[guild_id] = None
            return

        if len(queue) > 0:
            next_track = queue.pop(0)
            self.current_tracks[guild_id] = next_track

            try:
                source = await YTDLSource.from_url(next_track['query'], loop=self.bot.loop, stream=True)
                settings = get_music_settings(ctx)
                volume = settings.get("music_volume", 100) / 100.0
                source.volume = volume

                voice_client.play(source, after=lambda e: self.play_next(ctx))
                
                embed = discord.Embed(title="🎵 Odtwarzanie", color=0x74b816)
                embed.add_field(name="Tytuł", value=f"**{source.title}**", inline=False)
                embed.add_field(name="Długość", value=self.format_duration(source.duration), inline=True)
                embed.add_field(name="Dodano przez", value=next_track['requester'], inline=True)
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"❌ Wystąpił błąd podczas próby odtworzenia utworu `{next_track['title']}`: {e}")
                self.play_next(ctx)
        else:
            self.current_tracks[guild_id] = None
            # Wyłączenie po bezczynności, jeśli nie ma włączonego trybu 24/7
            settings = get_music_settings(ctx)
            if not settings.get("music_247", False):
                await asyncio.sleep(15)
                # Sprawdzamy czy nadal nic nie gra i kolejka jest pusta
                if voice_client and not voice_client.is_playing() and len(self.get_queue(guild_id)) == 0:
                    await voice_client.disconnect()
                    await ctx.send("💤 Opuściłem kanał z powodu nieaktywności.")

    @commands.hybrid_command(name="join", description="Dołącza bota do wskazanego lub Twojego kanału głosowego.")
    @check_music_enabled()
    async def join(self, ctx, kanal: discord.VoiceChannel = None):
        await ctx.defer()
        target_channel = kanal
        
        if not target_channel:
            if ctx.author.voice and ctx.author.voice.channel:
                target_channel = ctx.author.voice.channel
            else:
                await ctx.send("❌ Musisz podać kanał głosowy lub dołączyć do jednego z nich, aby bot mógł wejść!")
                return
                
        voice_client = ctx.guild.voice_client
        if voice_client:
            if voice_client.channel.id == target_channel.id:
                await ctx.send(f"ℹ️ Jestem już na kanale {target_channel.mention}!")
                return
            try:
                await voice_client.move_to(target_channel)
                await ctx.send(f"↪️ Przeniosłem się na kanał {target_channel.mention}!")
            except Exception as e:
                print(f"[VOICE] Błąd przenoszenia na kanał {target_channel.name}: {e}")
                await ctx.send(f"❌ Nie udało się przenieść na kanał {target_channel.mention}: `{e}`")
        else:
            try:
                await target_channel.connect(timeout=10.0)
                await ctx.send(f"👋 Połączyłem się z kanałem {target_channel.mention}!")
            except Exception as e:
                print(f"[VOICE] Błąd łączenia z kanałem {target_channel.name}: {e}")
                await ctx.send(f"❌ Nie udało się połączyć z kanałem {target_channel.mention}: `{e}`")

    @commands.hybrid_command(name="leave", description="Rozłącza bota z kanału głosowego.")
    @check_music_enabled()
    async def leave(self, ctx):
        await ctx.defer()
        voice_client = ctx.guild.voice_client
        if not voice_client:
            await ctx.send("❌ Nie jestem połączony z żadnym kanałem głosowym!")
            return
            
        guild_id = ctx.guild.id
        self.current_tracks[guild_id] = None
        self.paused[guild_id] = False
        self.queues[guild_id] = []
        
        try:
            await voice_client.disconnect()
            await ctx.send("👋 Opuściłem kanał głosowy.")
        except Exception as e:
            print(f"[VOICE] Błąd rozłączania: {e}")
            await ctx.send(f"❌ Wystąpił błąd podczas rozłączania: `{e}`")

    @commands.hybrid_command(name="play", description="Odtwarza utwór z YouTube lub wyszukuje frazę.")
    @check_music_enabled()
    async def play(self, ctx, *, utwor: str):
        await ctx.defer()
        
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ Musisz znajdować się na kanale głosowym, aby odtwarzać muzykę!")
            return

        voice_channel = ctx.author.voice.channel
        
        voice_client = ctx.guild.voice_client
        if not voice_client:
            try:
                voice_client = await voice_channel.connect(timeout=10.0)
            except Exception as e:
                print(f"[VOICE] Błąd łączenia z kanałem {voice_channel.name}: {e}")
                await ctx.send(f"❌ Nie udało się połączyć z kanałem głosowym: `{e}`")
                return

        # Szybkie pobranie metadanych
        try:
            loop = self.bot.loop or asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(utwor, download=False, process=False))
            
            title = utwor
            if 'entries' in data:
                # Jeśli to wyszukiwanie, robimy pełny ekstrakt (bez pobierania pliku)
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(utwor, download=False))
                if 'entries' in data and len(data['entries']) > 0:
                    data = data['entries'][0]
            elif 'title' not in data:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(utwor, download=False))

            title = data.get('title', utwor)
            duration = self.format_duration(data.get('duration'))
            url = data.get('webpage_url', data.get('url', ''))
        except Exception as e:
            title = utwor
            duration = "N/A"
            url = ""

        track = {
            "title": title,
            "duration": duration,
            "requester": ctx.author.mention,
            "url": url,
            "query": utwor
        }
        
        queue = self.get_queue(ctx.guild.id)
        
        if not voice_client.is_playing() and not voice_client.is_paused():
            self.current_tracks[ctx.guild.id] = track
            try:
                source = await YTDLSource.from_url(utwor, loop=self.bot.loop, stream=True)
                settings = get_music_settings(ctx)
                volume = settings.get("music_volume", 100) / 100.0
                source.volume = volume
                
                voice_client.play(source, after=lambda e: self.play_next(ctx))
                
                embed = discord.Embed(title="🎵 Odtwarzanie", color=0x74b816)
                embed.add_field(name="Tytuł", value=f"**{source.title}**", inline=False)
                embed.add_field(name="Długość", value=self.format_duration(source.duration), inline=True)
                embed.add_field(name="Dodano przez", value=track['requester'], inline=True)
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"❌ Wystąpił błąd podczas próby odtworzenia utworu: {e}")
                self.current_tracks[ctx.guild.id] = None
        else:
            queue.append(track)
            embed = discord.Embed(title="📥 Dodano do kolejki", color=0x74b816)
            embed.add_field(name="Tytuł", value=f"**{track['title']}**", inline=False)
            embed.add_field(name="Pozycja w kolejce", value=str(len(queue)), inline=True)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", description="Pomija aktualny utwór.")
    @check_music_enabled()
    async def skip(self, ctx):
        await ctx.defer()
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        
        if not self.current_tracks.get(guild_id):
            await ctx.send("❌ Aktualnie nic nie jest odtwarzane!")
            return
            
        old_track = self.current_tracks[guild_id]
        voice_client = ctx.guild.voice_client
        
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await ctx.send(f"⏭️ Pominięto: **{old_track['title']}**.")
        else:
            if len(queue) > 0:
                next_track = queue.pop(0)
                self.current_tracks[guild_id] = next_track
                await ctx.send(f"⏭️ Pominięto: **{old_track['title']}**. Przechodzę do następnego.")
                self.play_next(ctx)
            else:
                self.current_tracks[guild_id] = None
                await ctx.send(f"⏭️ Pominięto: **{old_track['title']}**. Kolejka jest pusta.")

    @commands.hybrid_command(name="stop", description="Zatrzymuje odtwarzanie i czyści kolejkę.")
    @check_music_enabled()
    async def stop(self, ctx):
        await ctx.defer()
        guild_id = ctx.guild.id
        self.queues[guild_id] = []
        self.current_tracks[guild_id] = None
        self.paused[guild_id] = False
        
        voice_client = ctx.guild.voice_client
        if voice_client:
            voice_client.stop()
            await voice_client.disconnect()
            
        await ctx.send("🛑 Zatrzymano odtwarzanie, wyczyszczono kolejkę i rozłączono bota.")

    @commands.hybrid_command(name="queue", description="Pokazuje aktualną kolejkę utworów.")
    @check_music_enabled()
    async def queue(self, ctx):
        await ctx.defer()
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        current = self.current_tracks.get(guild_id)
        
        if not current:
            await ctx.send("❌ Kolejka jest pusta i nic nie jest teraz odtwarzane!")
            return
            
        embed = discord.Embed(title="📋 Kolejka utworów", color=0x74b816)
        embed.add_field(name="Gra teraz", value=f"🎵 **{current['title']}** | Dodane przez: {current['requester']}", inline=False)
        
        if len(queue) > 0:
            queue_list = ""
            for idx, track in enumerate(queue[:10], start=1):
                queue_list += f"`{idx}.` **{track['title']}** ({track['duration']}) - dodane przez: {track['requester']}\n"
            if len(queue) > 10:
                queue_list += f"\n*i {len(queue) - 10} więcej utworów...*"
            embed.add_field(name="Nadchodzące", value=queue_list, inline=False)
        else:
            embed.add_field(name="Nadchodzące", value="Brak utworów w kolejce. Użyj `/play`, aby dodać więcej!", inline=False)
            
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", description="Pokazuje szczegóły aktualnie odtwarzanego utworu.")
    @check_music_enabled()
    async def nowplaying(self, ctx):
        await ctx.defer()
        current = self.current_tracks.get(ctx.guild.id)
        if not current:
            await ctx.send("❌ Aktualnie nic nie jest odtwarzane!")
            return
            
        embed = discord.Embed(title="📻 Aktualnie grane", color=0x74b816)
        embed.add_field(name="Tytuł", value=f"**{current['title']}**", inline=False)
        embed.add_field(name="Długość", value=current['duration'], inline=True)
        embed.add_field(name="Kolejka", value=f"{len(self.get_queue(ctx.guild.id))} utworów", inline=True)
        embed.add_field(name="Zażądane przez", value=current['requester'], inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="volume", description="Zmienia głośność odtwarzacza (10-100%).")
    @check_music_enabled()
    async def volume(self, ctx, glosnosc: int):
        await ctx.defer()
        if not (10 <= glosnosc <= 100):
            await ctx.send("❌ Głośność musi mieścić się w przedziale od 10% do 100%!")
            return
            
        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.source:
            voice_client.source.volume = glosnosc / 100.0
            
        await ctx.send(f"🔊 Głośność odtwarzacza została zmieniona na **{glosnosc}%**.")

    @commands.hybrid_command(name="lyrics", description="Wyszukuje tekst dla aktualnego lub podanego utworu.")
    @check_music_enabled()
    async def lyrics(self, ctx, utwor: str = None):
        await ctx.defer()
        song_title = utwor
        if not song_title:
            current = self.current_tracks.get(ctx.guild.id)
            if current:
                song_title = current['title']
            else:
                await ctx.send("❌ Podaj nazwę utworu lub włącz odtwarzanie!")
                return
                
        await ctx.send(f"🔍 Tekst dla utworu **{song_title}**:\n*(Funkcja wyszukiwania tekstu piosenek zostanie dodana w przyszłości)*")

    @commands.hybrid_command(name="shuffle", description="Miesza kolejność utworów w kolejce.")
    @check_music_enabled()
    async def shuffle(self, ctx):
        await ctx.defer()
        import random
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        
        if len(queue) < 2:
            await ctx.send("❌ Kolejka musi mieć przynajmniej 2 utwory, aby ją przemieszać!")
            return
            
        random.shuffle(queue)
        await ctx.send("🔀 Kolejka utworów została przemieszana!")

    @commands.hybrid_command(name="pause", description="Wstrzymuje odtwarzanie muzyki.")
    @check_music_enabled()
    async def pause(self, ctx):
        await ctx.defer()
        guild_id = ctx.guild.id
        voice_client = ctx.guild.voice_client
        
        if not voice_client or not voice_client.is_playing():
            await ctx.send("❌ Odtwarzacz nie gra żadnej muzyki!")
            return
            
        voice_client.pause()
        self.paused[guild_id] = True
        await ctx.send("⏸️ Odtwarzanie wstrzymane. Użyj `/resume`, aby wznowić.")

    @commands.hybrid_command(name="resume", description="Wznawia wstrzymane odtwarzanie muzyki.")
    @check_music_enabled()
    async def resume(self, ctx):
        await ctx.defer()
        guild_id = ctx.guild.id
        voice_client = ctx.guild.voice_client
        
        if not voice_client or not voice_client.is_paused():
            await ctx.send("❌ Odtwarzacz nie jest wstrzymany!")
            return
            
        voice_client.resume()
        self.paused[guild_id] = False
        await ctx.send("▶️ Wznowiono odtwarzanie muzyki.")

async def setup(bot):
    await bot.add_cog(Music(bot))
