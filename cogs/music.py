import discord
from discord.ext import commands
import asyncio
from database import get_settings, is_command_enabled

def check_music_enabled():
    async def predicate(ctx):
        if not ctx.guild:
            return False
        
        # 1. Sprawdzamy czy cały moduł muzyczny jest włączony na serwerze
        settings = get_settings(str(ctx.guild.id))
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
        # Słownik przechowujący kolejki odtwarzania per serwer: guild_id -> list of dicts
        self.queues = {}
        # Słownik przechowujący aktualnie odtwarzany utwór: guild_id -> dict
        self.current_tracks = {}
        # Słownik przechowujący status pauzy: guild_id -> bool
        self.paused = {}

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    @commands.hybrid_command(name="play", description="Odtwarza utwór z YouTube/Spotify lub wyszukuje frazę.")
    @check_music_enabled()
    async def play(self, ctx, *, utwor: str):
        await ctx.defer()
        
        # Sprawdzamy czy użytkownik jest na kanale głosowym
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ Musisz znajdować się na kanale głosowym, aby odtwarzać muzykę!")
            return

        voice_channel = ctx.author.voice.channel
        
        # Symulacja wyszukiwania i odtwarzania
        mock_track = {
            "title": utwor,
            "duration": "3:45",
            "requester": ctx.author.mention,
            "url": "https://youtube.com/watch?v=mock"
        }
        
        queue = self.get_queue(ctx.guild.id)
        
        # Łączenie z kanałem głosowym (próba)
        voice_client = ctx.guild.voice_client
        voice_connected = True
        if not voice_client:
            try:
                # Wymaga PyNaCl, jeśli go nie ma, złapie błąd i powiadomi
                await voice_channel.connect()
            except Exception as e:
                # Brak bibliotek głosowych w systemie - działamy w trybie symulacji tekstowej
                voice_connected = False

        if len(queue) == 0 and not self.current_tracks.get(ctx.guild.id):
            self.current_tracks[ctx.guild.id] = mock_track
            
            embed = discord.Embed(title="🎵 Odtwarzanie", color=0x74b816)
            embed.add_field(name="Tytuł", value=f"**{mock_track['title']}**", inline=False)
            embed.add_field(name="Długość", value=mock_track['duration'], inline=True)
            embed.add_field(name="Dodano przez", value=mock_track['requester'], inline=True)
            
            if not voice_connected:
                embed.set_footer(text="Tryb demonstracyjny (brak biblioteki PyNaCl w środowisku bota)")
                
            await ctx.send(embed=embed)
        else:
            queue.append(mock_track)
            embed = discord.Embed(title="📥 Dodano do kolejki", color=0x74b816)
            embed.add_field(name="Tytuł", value=f"**{mock_track['title']}**", inline=False)
            embed.add_field(name="Pozycja w kolejce", value=str(len(queue)), inline=True)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", description="Pomija aktualny utwór.")
    @check_music_enabled()
    async def skip(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        
        if not self.current_tracks.get(guild_id):
            await ctx.send("❌ Aktualnie nic nie jest odtwarzane!")
            return
            
        old_track = self.current_tracks[guild_id]
        
        if len(queue) > 0:
            next_track = queue.pop(0)
            self.current_tracks[guild_id] = next_track
            
            embed = discord.Embed(title="⏭️ Pominięto utwór", description=f"Pominięto: **{old_track['title']}**", color=0x74b816)
            embed.add_field(name="Teraz gramy", value=f"**{next_track['title']}**", inline=False)
            embed.add_field(name="Zażądane przez", value=next_track['requester'], inline=True)
            await ctx.send(embed=embed)
        else:
            self.current_tracks[guild_id] = None
            self.paused[guild_id] = False
            
            # Odłączamy się od kanału
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.disconnect()
                
            await ctx.send(f"⏭️ Pominięto: **{old_track['title']}**. Kolejka jest pusta. Bot opuścił kanał głosowy.")

    @commands.hybrid_command(name="stop", description="Zatrzymuje odtwarzanie i czyści kolejkę.")
    @check_music_enabled()
    async def stop(self, ctx):
        guild_id = ctx.guild.id
        self.queues[guild_id] = []
        self.current_tracks[guild_id] = None
        self.paused[guild_id] = False
        
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
            
        await ctx.send("🛑 Zatrzymano odtwarzanie, wyczyszczono kolejkę i rozłączono bota.")

    @commands.hybrid_command(name="queue", description="Pokazuje aktualną kolejkę utworów.")
    @check_music_enabled()
    async def queue(self, ctx):
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
        if not (10 <= glosnosc <= 100):
            await ctx.send("❌ Głośność musi mieścić się w przedziale od 10% do 100%!")
            return
            
        # Zapisujemy głośność w sesji i bazie danych (opcjonalnie, tu tylko potwierdzamy zmianę)
        await ctx.send(f"🔊 Głośność odtwarzacza została zmieniona na **{glosnosc}%**.")

    @commands.hybrid_command(name="lyrics", description="Wyszukuje tekst dla aktualnego lub podanego utworu.")
    @check_music_enabled()
    async def lyrics(self, ctx, utwor: str = None):
        song_title = utwor
        if not song_title:
            current = self.current_tracks.get(ctx.guild.id)
            if current:
                song_title = current['title']
            else:
                await ctx.send("❌ Podaj nazwę utworu lub włącz odtwarzanie!")
                return
                
        await ctx.send(f"🔍 Tekst dla utworu **{song_title}**:\n*(Tutaj pojawia się tekst piosenki, funkcja demonstracyjna)*")

    @commands.hybrid_command(name="shuffle", description="Miesza kolejność utworów w kolejce.")
    @check_music_enabled()
    async def shuffle(self, ctx):
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
        guild_id = ctx.guild.id
        if self.paused.get(guild_id):
            await ctx.send("❌ Odtwarzacz jest już wstrzymany!")
            return
            
        self.paused[guild_id] = True
        await ctx.send("⏸️ Odtwarzanie wstrzymane. Użyj `/resume`, aby wznowić.")

    @commands.hybrid_command(name="resume", description="Wznawia wstrzymane odtwarzanie muzyki.")
    @check_music_enabled()
    async def resume(self, ctx):
        guild_id = ctx.guild.id
        if not self.paused.get(guild_id):
            await ctx.send("❌ Odtwarzacz nie jest wstrzymany!")
            return
            
        self.paused[guild_id] = False
        await ctx.send("▶️ Wznowiono odtwarzanie muzyki.")

async def setup(bot):
    await bot.add_cog(Music(bot))
