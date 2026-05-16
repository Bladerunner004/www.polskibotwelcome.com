import discord
from discord.ext import commands
import datetime
import json
import re
from database import get_settings, add_audit_log, log_message_activity, log_join_activity, add_warning, get_warnings, clear_warnings
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

    async def do_confirm(self, ctx, text):
        settings = get_settings(str(ctx.guild.id))
        confirm = settings.get('moderation_confirm', False)
        await ctx.send(text, ephemeral=not confirm)

    @commands.hybrid_command(name="ban", description="Zbanuj użytkownika.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.ban(uzytkownik, reason=powod)
        await self.do_confirm(ctx, f"🔨 Zbanowano {uzytkownik.mention}. Powód: {powod}")
        add_audit_log(ctx.guild.id, "Moderacja", ctx.author.name, ctx.author.id, "BAN", f"Zbanowano {uzytkownik.name} ({uzytkownik.id})")

    @commands.hybrid_command(name="unban", description="Odbanuj użytkownika.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, uzytkownik_id: str):
        try:
            user = await self.bot.fetch_user(int(uzytkownik_id))
            await ctx.guild.unban(user)
            await self.do_confirm(ctx, f"✅ Odbanowano użytkownika o ID {uzytkownik_id}.")
        except:
            await ctx.send("❌ Nie znaleziono użytkownika o podanym ID.", ephemeral=True)

    @commands.hybrid_command(name="kick", description="Wyrzuć użytkownika.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.kick(uzytkownik, reason=powod)
        await self.do_confirm(ctx, f"👢 Wyrzucono {uzytkownik.mention}. Powód: {powod}")

    @commands.hybrid_command(name="mute", description="Wycisz użytkownika (Timeout).")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, uzytkownik: discord.Member, minuty: int, *, powod: str = "Brak"):
        duration = datetime.timedelta(minutes=minuty)
        await uzytkownik.timeout(duration, reason=powod)
        await self.do_confirm(ctx, f"🔇 Wyciszono {uzytkownik.mention} na {minuty} min. Powód: {powod}")

    @commands.hybrid_command(name="unmute", description="Zdejmij wyciszenie.")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, uzytkownik: discord.Member):
        await uzytkownik.timeout(None)
        await self.do_confirm(ctx, f"🔊 Zdjęto wyciszenie z {uzytkownik.mention}.")

    @commands.hybrid_command(name="warn", description="Nadaj ostrzeżenie użytkownikowi.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        add_warning(ctx.guild.id, uzytkownik.id, ctx.author.id, powod)
        await self.do_confirm(ctx, f"⚠️ Nadano ostrzeżenie dla {uzytkownik.mention}. Powód: {powod}")

    @commands.hybrid_command(name="warns", description="Sprawdź ostrzeżenia użytkownika.")
    async def warns(self, ctx, uzytkownik: discord.Member):
        warnings = get_warnings(ctx.guild.id, uzytkownik.id)
        if not warnings:
            return await ctx.send(f"✅ {uzytkownik.mention} nie ma żadnych ostrzeżeń.", ephemeral=True)
        
        embed = discord.Embed(title=f"Ostrzeżenia: {uzytkownik.name}", color=0xffa500)
        for i, w in enumerate(warnings, 1):
            embed.add_field(name=f"#{i} | Moderator: {w['moderator_id']}", value=f"Powód: {w['reason']}\nData: {w['timestamp']}", inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="clear", description="Usuń określoną liczbę wiadomości.")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, ilosc: int):
        await ctx.channel.purge(limit=ilosc + 1)
        await ctx.send(f"🧹 Usunięto {ilosc} wiadomości.", delete_after=5)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        settings = get_settings(str(message.guild.id))
        
        # Automatyczna Moderacja: Wulgaryzmy
        if settings.get("automod_badwords"):
            custom_list = settings.get("automod_badwords_list", [])
            all_bad = GLOBAL_BADWORDS + custom_list
            if any(word.lower() in message.content.lower() for word in all_bad):
                if not message.author.guild_permissions.manage_messages:
                    try:
                        await message.delete()
                        await message.channel.send(f"⚠️ {message.author.mention}, Twoja wiadomość zawierała niedozwolone słowa!", delete_after=5)
                    except: pass

        # Logowanie aktywności (statystyki)
        log_message_activity(message.guild.id, message.channel.id)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
