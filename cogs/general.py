import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="info", description="Informacje o bocie.")
    async def info(self, ctx):
        embed = discord.Embed(
            title="🤖 Polski Bot",
            description="Zaawansowany bot do zarządzania serwerem.\n\n🌐 [Panel WWW](https://polskibot.pl)",
            color=0x74b816
        )
        embed.add_field(name="🏠 Serwery", value=f"{len(self.bot.guilds)}", inline=True)
        embed.add_field(name="⚡ Ping", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pomoc", description="Lista komend.")
    async def pomoc(self, ctx):
        embed = discord.Embed(title="📖 Pomoc Polski Bot", color=0x74b816)
        embed.add_field(name="🎟️ Zarządzanie", value="`/ticket`, `/claim`, `/close`", inline=False)
        embed.add_field(name="🛡️ Moderacja", value="`/ban`, `/kick`, `/mute`, `/clear`", inline=False)
        embed.add_field(name="📊 Poziomy", value="`/level`, `/exp`", inline=False)
        embed.add_field(name="🎮 Zabawa", value="`/iq`, `/cat`, `/slap`", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
