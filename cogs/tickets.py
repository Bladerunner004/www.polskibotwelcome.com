import discord
from discord.ext import commands
from discord import ui
import datetime
from database import get_settings, add_audit_log

class TicketActions(ui.View):
    def __init__(self, staff_role_id=None):
        super().__init__(timeout=None)
        self.staff_role_id = staff_role_id

    @ui.button(label="🙋 Przejmij", style=discord.ButtonStyle.green, custom_id="claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: ui.Button):
        if self.staff_role_id:
            role = interaction.guild.get_role(int(self.staff_role_id))
            if role and role not in interaction.user.roles and not interaction.user.guild_permissions.manage_channels:
                return await interaction.response.send_message("❌ Tylko personel może przejąć to zgłoszenie!", ephemeral=True)
        
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, view_channel=True)
        await interaction.channel.send(f"🙋 **{interaction.user.mention}** przejął to zgłoszenie!")
        button.disabled = True
        await interaction.response.edit_message(view=self)

    @ui.button(label="🔒 Zamknij", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            if self.staff_role_id:
                role = interaction.guild.get_role(int(self.staff_role_id))
                if role and role not in interaction.user.roles:
                    return await interaction.response.send_message("❌ Brak uprawnień do zamknięcia!", ephemeral=True)

        await interaction.response.send_message("🔒 Zgłoszenie zostanie zamknięte za 5 sekund...")
        
        # Logowanie zamknięcia
        settings = get_settings(str(interaction.guild.id))
        log_ch_id = settings.get("ticket_logs_channel_id")
        if log_ch_id:
            log_ch = interaction.guild.get_channel(int(log_ch_id))
            if log_ch:
                emb = discord.Embed(title="🔒 Bilet Zamknięty", color=discord.Color.red(), timestamp=datetime.datetime.now())
                emb.add_field(name="Kanał", value=interaction.channel.name)
                emb.add_field(name="Zamknął", value=interaction.user.mention)
                await log_ch.send(embed=emb)

        await discord.utils.sleep_until(datetime.datetime.now() + datetime.timedelta(seconds=5))
        await interaction.channel.delete()

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ticket", description="Otwórz nowe zgłoszenie.")
    async def ticket(self, ctx, tytul: str = "Brak tytułu", *, sprawa: str = "Brak opisu"):
        settings = get_settings(str(ctx.guild.id))
        if not settings.get("ticket_enabled", 1):
            return await ctx.send("❌ System biletów jest wyłączony!", ephemeral=True)

        # Sprawdzenie limitu
        limit = settings.get("ticket_limit", 1)
        existing = [ch for ch in ctx.guild.text_channels if ch.name.startswith(f"ticket-{ctx.author.name.lower()}")]
        if len(existing) >= limit:
            return await ctx.send(f"❌ Masz już {len(existing)} otwarte zgłoszenia!", ephemeral=True)

        category = None
        cat_id = settings.get("ticket_category_id")
        if cat_id: category = ctx.guild.get_channel(int(cat_id))

        staff_role_id = settings.get("ticket_staff_role_id")
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        if staff_role_id:
            staff_role = ctx.guild.get_role(int(staff_role_id))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)

        channel = await ctx.guild.create_text_channel(
            f"ticket-{ctx.author.name.lower()}",
            category=category,
            overwrites=overwrites,
            reason=f"Bilet utworzony przez {ctx.author}"
        )

        msg_title = settings.get("ticket_msg_title", "Nowe Zgłoszenie").replace("{user}", ctx.author.name)
        msg_desc = settings.get("ticket_msg_desc", "Zaraz ktoś Ci pomoże.").replace("{user}", ctx.author.mention)

        embed = discord.Embed(title=msg_title, description=f"{msg_desc}\n\n**Temat:** {tytul}\n**Opis:** {sprawa}", color=discord.Color.blue())
        embed.set_footer(text=f"ID Użytkownika: {ctx.author.id}")
        
        await channel.send(f"{ctx.author.mention}", embed=embed, view=TicketActions(staff_role_id))
        await ctx.send(f"✅ Otwarto zgłoszenie: {channel.mention}", ephemeral=True)
        
        # Logowanie otwarcia
        log_ch_id = settings.get("ticket_logs_channel_id")
        if log_ch_id:
            log_ch = ctx.guild.get_channel(int(log_ch_id))
            if log_ch:
                log_emb = discord.Embed(title="🎫 Nowy Bilet", color=discord.Color.green(), timestamp=datetime.datetime.now())
                log_emb.add_field(name="Użytkownik", value=ctx.author.mention)
                log_emb.add_field(name="Kanał", value=channel.mention)
                await log_ch.send(embed=log_emb)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
