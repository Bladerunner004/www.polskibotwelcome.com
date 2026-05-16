import discord
from discord.ext import commands
import datetime
import json
import re
from database import get_settings, add_audit_log, log_message_activity, log_join_activity
from badwords_list import GLOBAL_BADWORDS

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_log(self, guild, category, embed):
        settings = get_settings(str(guild.id))
        ch_id = settings.get('logs_channel_id')
        if not ch_id or not settings.get(f"logs_{category}", False): return
        channel = guild.get_channel(int(ch_id))
        if channel: await channel.send(embed=embed)

    @commands.hybrid_command(name="ban", description="Zbanuj użytkownika.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.ban(uzytkownik, reason=powod)
        await ctx.send(f"🔨 Zbanowano {uzytkownik.mention}.", ephemeral=True)

    @commands.hybrid_command(name="kick", description="Wyrzuć użytkownika.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.kick(uzytkownik, reason=powod)
        await ctx.send(f"👢 Wyrzucono {uzytkownik.mention}.", ephemeral=True)

    @commands.hybrid_command(name="mute", description="Wycisz użytkownika.")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, uzytkownik: discord.Member, minuty: int, *, powod: str = "Brak"):
        duration = datetime.timedelta(minutes=minuty)
        await uzytkownik.timeout(duration, reason=powod)
        await ctx.send(f"🔇 Wyciszono {uzytkownik.mention} na {minuty} min.", ephemeral=True)

    @commands.hybrid_command(name="clear", description="Usuń wiadomości.")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, ilosc: int):
        await ctx.channel.purge(limit=ilosc + 1)
        await ctx.send(f"🧹 Usunięto {ilosc} wiadomości.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        settings = get_settings(str(message.guild.id))
        if settings.get("automod_badwords"):
            custom_list = json.loads(settings.get("automod_badwords_list", "[]"))
            if any(word.lower() in message.content.lower() for word in (GLOBAL_BADWORDS + custom_list)):
                if not message.author.guild_permissions.manage_messages:
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention}, uważaj na słowa!", delete_after=5)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
