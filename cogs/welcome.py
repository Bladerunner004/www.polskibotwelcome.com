import discord
from discord.ext import commands
import io
import aiohttp
from utils.image_gen import generate_welcome_card, fix_url

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def send_welcome_message(self, guild: discord.Guild, member: discord.Member, config_type: str, target_id=None, is_test=False):
        from database import get_welcome_configs, get_settings, get_global_color
        configs = get_welcome_configs(str(guild.id), config_type)
        if not configs: return

        if target_id is not None:
            configs = [c for c in configs if str(c['id']) == str(target_id)]
            if not configs: return

        tag_map = {
            "{nick}": member.name,
            "{mention}": member.mention,
            "{tag}": str(member),
            "{server}": guild.name,
            "{count}": str(guild.member_count),
        }

        def replace_tags(text):
            if not text: return ""
            for tag, val in tag_map.items():
                text = text.replace(tag, val)
            return text

        sent_channels = set()
        for cfg in configs:
            if not cfg.get('is_enabled', 1): continue
            ch_id_str = str(cfg.get('channel_id', ''))
            if ch_id_str in sent_channels: continue
            
            channel = guild.get_channel(int(ch_id_str)) if ch_id_str.isdigit() else None
            if not channel: continue
            
            sent_channels.add(ch_id_str)
            content = replace_tags(cfg.get('plain_text', ''))

            try:
                embed = None
                if cfg.get('is_embed'):
                    desc = replace_tags(cfg.get('description', ''))
                    title = replace_tags(cfg.get('title', ''))
                    footer = replace_tags(cfg.get('footer', ''))
                    
                    color_val = get_global_color(guild.id)
                    if cfg.get('color'):
                        try: color_val = int(cfg['color'].replace('#', ''), 16)
                        except: pass
                        
                    embed = discord.Embed(title=title, description=desc, color=color_val)
                    if cfg.get('author'): embed.set_author(name=replace_tags(cfg['author']))
                    if footer: embed.set_footer(text=footer)
                
                file = None
                if cfg.get('has_image'):
                    bg_url = cfg.get('bg_url', '')
                    res = await generate_welcome_card(
                        bg_url, 
                        member.display_avatar.url, 
                        replace_tags(cfg.get('line1', 'WITAJ')),
                        replace_tags(cfg.get('line2', '{nick}')),
                        font_name=cfg.get('font_name', 'arialbd.ttf'),
                        text_color=cfg.get('img_text_color', '#ffffff'),
                        has_frame=cfg.get('has_frame', 0)
                    )
                    if res:
                        img_buffer, ext = res
                        fname = f"welcome.{ext}"
                        file = discord.File(fp=img_buffer, filename=fname)
                        if embed: embed.set_image(url=f"attachment://{fname}")

                prefix = "🧪 **TEST: **" if is_test else ""
                await channel.send(content=f"{prefix}{content}" if content or prefix else None, embed=embed, file=file)
            except Exception as e:
                print(f"⚠️ [COGS/WELCOME] Błąd: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            from database import log_join_activity
            log_join_activity(member.guild.id)
        except Exception as e:
            print(f"⚠️ [COGS/WELCOME] Błąd log_join_activity: {e}")
        await self.send_welcome_message(member.guild, member, 'powitanie')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.send_welcome_message(member.guild, member, 'pozegnanie')

async def setup(bot):
    await bot.add_cog(Welcome(bot))
