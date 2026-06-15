import discord
from discord.ext import commands
import random
import time
from database import get_user_level, add_xp, get_settings

class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        settings = get_settings(str(message.guild.id))
        if settings.get("levels_enabled", 1):
            user_data = get_user_level(message.guild.id, message.author.id)
            if time.time() - user_data['last_msg_at'] > 60:
                xp_gain = random.randint(15, 25)
                leveled_up, new_lvl = add_xp(message.guild.id, message.author.id, xp_gain)
                if leveled_up and settings.get("level_up_msg_enabled", 1):
                    # Wybór kanału dla powiadomienia
                    target_channel = message.channel
                    ch_id = settings.get("level_up_channel_id")
                    if ch_id and str(ch_id).isdigit():
                        custom_ch = message.guild.get_channel(int(ch_id))
                        if custom_ch: target_channel = custom_ch

                    embed = discord.Embed(
                        title="🎉 NOWY POZIOM!",
                        color=0x74b816,
                        description=f"Gratulacje {message.author.mention}!\nAwansowałeś na **{new_lvl} Poziom** na tym serwerze! 🚀"
                    )
                    embed.set_thumbnail(url=message.author.display_avatar.url)
                    avatar_url = self.bot.user.avatar.url if self.bot.user and self.bot.user.avatar else None
                    embed.set_footer(text="PolskiBot System Poziomów", icon_url=avatar_url)
                    await target_channel.send(content=message.author.mention, embed=embed)

    @commands.hybrid_command(name="level", description="Sprawdź swój poziom.")
    async def level(self, ctx, uzytkownik: discord.Member = None):
        uzytkownik = uzytkownik or ctx.author
        data = get_user_level(ctx.guild.id, uzytkownik.id)
        await ctx.send(f"📊 {uzytkownik.display_name} posiada obecnie **{data['level']} Level**.")

    @commands.hybrid_command(name="exp", description="Sprawdź swoje XP.")
    async def exp(self, ctx):
        data = get_user_level(ctx.guild.id, ctx.author.id)
        await ctx.send(f"✨ Masz obecnie **{data['xp']} XP**.")

async def setup(bot):
    await bot.add_cog(Levels(bot))
