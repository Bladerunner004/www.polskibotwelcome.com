import discord
from discord.ext import commands
from discord import ui

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

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ticket", description="Otwórz nowe zgłoszenie.")
    async def ticket(self, ctx, tytul: str, sprawa: str):
        channel = await ctx.guild.create_text_channel(
            f"ticket-{ctx.author.name.lower()}",
            overwrites={
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        embed = discord.Embed(title=f"📢 {tytul}", description=f"Witaj {ctx.author.mention}!\n\n**Sprawa:** {sprawa}", color=0x3498db)
        await channel.send(embed=embed, view=TicketActions())
        await ctx.send(f"✅ Otwarto zgłoszenie: {channel.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
