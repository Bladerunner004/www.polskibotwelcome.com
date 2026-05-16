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
                if leveled_up:
                    await message.channel.send(f"🎉 Gratulacje {message.author.mention}! Awansowałeś na **{new_lvl} Poziom**!")

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
