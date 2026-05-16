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
        """Wysyła log na wybrany kanał Discord."""
        settings = get_settings(str(guild.id))
        ch_id = settings.get('logs_channel_id')
        if not ch_id or not settings.get(f"logs_{category}", False): return
        channel = guild.get_channel(int(ch_id))
        if channel: await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        settings = get_settings(str(message.guild.id))
        
        # --- ANTY-LINK ---
        if settings.get("automod_antilink"):
            if not message.author.guild_permissions.administrator:
                if re.search(r'(https?://\S+|discord\.gg/\S+)', message.content):
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention}, linki są zabronione!", delete_after=5)
                    return

        # --- ANTY-BADWORDS ---
        if settings.get("automod_badwords"):
            custom_list = json.loads(settings.get("automod_badwords_list", "[]"))
            if any(word.lower() in message.content.lower() for word in (GLOBAL_BADWORDS + custom_list)):
                if not message.author.guild_permissions.manage_messages:
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention}, uważaj na słowa!", delete_after=5)
                    return

        # --- ANTY-PHISHING ---
        if settings.get("automod_antiphishing"):
            if "discord.gift" in message.content.lower() and "free" in message.content.lower():
                if not message.author.guild_permissions.administrator:
                    await message.delete()
                    await message.channel.send(f"🛡️ {message.author.mention}, zablokowano potencjalny phishing!", delete_after=10)
                    return

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot: return
        emb = discord.Embed(title="🗑️ Usunięto wiadomość", color=0xe74c3c, timestamp=datetime.datetime.now())
        emb.add_field(name="Autor", value=f"{message.author} ({message.author.id})")
        emb.add_field(name="Kanał", value=message.channel.mention)
        emb.add_field(name="Treść", value=message.content[:1024] or "*Brak treści*", inline=False)
        await self.send_log(message.guild, "msg_updates", emb)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content: return
        emb = discord.Embed(title="📝 Edytowano wiadomość", color=0x3498db, timestamp=datetime.datetime.now())
        emb.add_field(name="Autor", value=f"{before.author} ({before.author.id})")
        emb.add_field(name="Przed", value=before.content[:1024] or "*Puste*", inline=False)
        emb.add_field(name="Po", value=after.content[:1024] or "*Puste*", inline=False)
        await self.send_log(before.guild, "msg_updates", emb)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
