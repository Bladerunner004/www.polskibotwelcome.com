import discord
from discord.ext import commands
from discord import ui
import json
import sqlite3

class SelfRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_selfrole_panel(self, channel, cfg, is_test=False):
        from database import DB_NAME, get_global_color
        from utils.image_gen import generate_framed_image, fix_url
        emb = discord.Embed(title=cfg.get('name', 'Panel Ról'), description=cfg.get('description', ''), color=get_global_color(channel.guild.id))
        
        file = None
        img_url = cfg.get('image_url')
        
        if img_url:
            has_frame = bool(cfg.get('has_frame'))
            res = await generate_framed_image(img_url, color=get_global_color(channel.guild.id), has_frame=has_frame)
            if res:
                img_data, ext = res
                fname = f"selfrole_img.{ext}"
                file = discord.File(img_data, filename=fname)
                emb.set_image(url=f"attachment://{fname}")
            else:
                emb.set_image(url=fix_url(img_url))

        if cfg.get('thumbnail_url'): emb.set_thumbnail(url=fix_url(cfg['thumbnail_url']))
        
        roles_data = json.loads(cfg.get('roles_json', '[]'))
        msg = None
        
        if not is_test and cfg.get('message_id'):
            try: msg = await channel.fetch_message(int(cfg['message_id']))
            except: pass

        if cfg['type'] == 'reaction':
            if msg: await msg.edit(embed=emb, attachments=[file] if file else [])
            else:
                msg = await channel.send(embed=emb, file=file)
                if not is_test:
                    conn = sqlite3.connect(DB_NAME)
                    conn.cursor().execute("UPDATE self_role_configs SET message_id = ? WHERE id = ?", (str(msg.id), cfg['id']))
                    conn.commit(); conn.close()
            for r in roles_data:
                try: await msg.add_reaction(r['emoji'])
                except: pass
        
        elif cfg['type'] == 'button':
            class RoleView(ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                    for r in roles_data:
                        btn = ui.Button(label=r.get('label', 'Rola'), emoji=r.get('emoji'), custom_id=f"selfrole_btn_{r['role_id']}")
                        self.add_item(btn)

            if msg: await msg.edit(embed=emb, view=RoleView(), attachments=[file] if file else [])
            else:
                msg = await channel.send(embed=emb, view=RoleView(), file=file)
                if not is_test:
                    conn = sqlite3.connect(DB_NAME)
                    conn.cursor().execute("UPDATE self_role_configs SET message_id = ? WHERE id = ?", (str(msg.id), cfg['id']))
                    conn.commit(); conn.close()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        custom_id = interaction.data.get('custom_id', '')
        
        if custom_id.startswith("selfrole_btn_"):
            role_id = int(custom_id.replace("selfrole_btn_", ""))
            role = interaction.guild.get_role(role_id)
            if not role: return await interaction.response.send_message("❌ Rola nie istnieje!", ephemeral=True)
            
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(f"✅ Odebrano rolę **{role.name}**.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"✅ Nadano rolę **{role.name}**.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id: return
        from database import get_selfrole_configs
        from cogs.embeds import emojis_match
        configs = get_selfrole_configs(payload.guild_id)
        for cfg in configs:
            if cfg['type'] == 'reaction' and str(payload.message_id) == str(cfg.get('message_id')):
                roles = json.loads(cfg['roles_json'])
                for r in roles:
                    if emojis_match(payload.emoji, r.get('emoji')):
                        guild = self.bot.get_guild(payload.guild_id)
                        if guild:
                            try:
                                role_id = int(r['role_id'])
                                role = guild.get_role(role_id)
                                member = payload.member or await guild.fetch_member(payload.user_id)
                                if role and member:
                                    await member.add_roles(role)
                                    print(f"✅ [COGS/SELFROLE] Nadano rolę {role.name} dla {member} przez reakcję")
                            except discord.Forbidden:
                                print(f"❌ [COGS/SELFROLE] Brak uprawnień do nadania roli {r.get('role_id')} przez reakcję. Upewnij się, że rola bota jest wyżej w hierarchii ról.")
                            except Exception as e:
                                print(f"⚠️ [COGS/SELFROLE] Nie można nadać roli przez reakcję: {e}")
                        break

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.user_id == self.bot.user.id: return
        from database import get_selfrole_configs
        from cogs.embeds import emojis_match
        configs = get_selfrole_configs(payload.guild_id)
        for cfg in configs:
            if cfg['type'] == 'reaction' and str(payload.message_id) == str(cfg.get('message_id')):
                roles = json.loads(cfg['roles_json'])
                for r in roles:
                    if emojis_match(payload.emoji, r.get('emoji')):
                        guild = self.bot.get_guild(payload.guild_id)
                        if guild:
                            try:
                                role_id = int(r['role_id'])
                                role = guild.get_role(role_id)
                                member = await guild.fetch_member(payload.user_id)
                                if role and member:
                                    await member.remove_roles(role)
                                    print(f"❌ [COGS/SELFROLE] Odebrano rolę {role.name} dla {member} przez usunięcie reakcji")
                            except discord.Forbidden:
                                print(f"❌ [COGS/SELFROLE] Brak uprawnień do odebrania roli {r.get('role_id')} przez usunięcie reakcji. Upewnij się, że rola bota jest wyżej w hierarchii ról.")
                            except Exception as e:
                                print(f"⚠️ [COGS/SELFROLE] Nie można odebrać roli przez usunięcie reakcji: {e}")
                        break

async def setup(bot):
    await bot.add_cog(SelfRole(bot))
