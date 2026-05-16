import discord
from discord.ext import commands
import random
import aiohttp

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="iq", description="Sprawdź swoje IQ.")
    async def iq(self, ctx):
        wynik = random.randint(50, 150)
        await ctx.send(f"🧠 Twoje IQ wynosi: **{wynik}**!")

    @commands.hybrid_command(name="cat", description="Losowy kotek.")
    async def cat(self, ctx):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.thecatapi.com/v1/images/search') as resp:
                data = await resp.json()
                embed = discord.Embed(title="🐱 Kotek!", color=0x3498db)
                embed.set_image(url=data[0]['url'])
                await ctx.send(embed=embed)

    @commands.hybrid_command(name="slap", description="Uderz kogoś!")
    async def slap(self, ctx, uzytkownik: discord.Member):
        await ctx.send(f"✋ {ctx.author.mention} uderzył {uzytkownik.mention}! Ałć!")

async def setup(bot):
    await bot.add_cog(Fun(bot))
