import discord
from discord.ext import commands
import json
import datetime
import sqlite3
from aiohttp import web
from utils.image_gen import generate_framed_image, fix_url

class Embeds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def do_process_embed_logic(self, data):
        """Zunifikowana logika wysyłania embedów (z ramkami, zasadami itp.)"""
        from database import get_embed_configs, DB_NAME, get_settings, get_global_color
        
        guild_id = data.get('guild_id')
        config_id = data.get('config_id')
        is_test = data.get('is_test', False)
        
        configs = get_embed_configs(guild_id)
        cfg = next((c for c in configs if str(c['id']) == str(config_id)), None)
        if not cfg: return {'success': False, 'error': 'Nie znaleziono configu'}
        
        guild = self.bot.get_guild(int(guild_id))
        if not guild: return {'success': False, 'error': 'Bot poza serwerem'}
        
        channel = guild.get_channel(int(cfg['channel_id']))
        if not channel: return {'success': False, 'error': 'Kanał nie istnieje'}

        embed_color = get_global_color(guild_id)
        if cfg.get('color'):
            try: embed_color = int(cfg['color'].replace('#', ''), 16)
            except: pass

        tag_map = {
            "{server}": guild.name,
            "{count}": str(guild.member_count),
            "{date}": datetime.datetime.now().strftime("%d.%m.%Y")
        }

        def replace_tags(text):
            if not text: return ""
            for tag, val in tag_map.items():
                text = text.replace(tag, val)
            return text

        embeds = []
        files = []
        
        # LOGIKA DLA ZASAD (RULES)
        if cfg.get('category') == 'rules':
            try:
                blocks = json.loads(cfg.get('description', '[]'))
                for i, block in enumerate(blocks):
                    # Jeśli jest zdjęcie w bloku, wysyłamy je w osobnym embedzie PRZED tekstem,
                    # by renderowało się na samej górze bloku, tak jak w panelu!
                    if block.get('image'):
                        img_eb = discord.Embed(color=embed_color)
                        if i == 0:
                            img_eb.title = replace_tags(cfg.get('name', 'Regulamin'))
                            if cfg.get('author'): img_eb.set_author(name=replace_tags(cfg['author']))
                        
                        if cfg.get('has_frame'):
                            res = await generate_framed_image(block['image'], width=600, height=200, color=embed_color)
                            if res:
                                img_data, ext = res
                                fname = f"rule_{i}.{ext}"
                                files.append(discord.File(img_data, filename=fname))
                                img_eb.set_image(url=f"attachment://{fname}")
                            else: img_eb.set_image(url=fix_url(block['image']))
                        else: img_eb.set_image(url=fix_url(block['image']))
                        embeds.append(img_eb)
                        
                        # Embed z tekstem (bez tytułu, bo tytuł poszedł już na obrazku na samej górze)
                        eb = discord.Embed(description=replace_tags(block.get('text', '')), color=embed_color)
                    else:
                        eb = discord.Embed(description=replace_tags(block.get('text', '')), color=embed_color)
                        if i == 0:
                            eb.title = replace_tags(cfg.get('name', 'Regulamin'))
                            if cfg.get('author'): eb.set_author(name=replace_tags(cfg['author']))
                    
                    if i == len(blocks) - 1:
                        if cfg.get('footer'): eb.set_footer(text=replace_tags(cfg['footer']))
                        if cfg.get('timestamp'): eb.timestamp = datetime.datetime.now()
                    embeds.append(eb)
            except Exception as e:
                print(f"❌ [COGS/EMBEDS] Błąd parsowania zasad: {e}")
        
        # STANDARDOWY EMBED
        else:
            title_val = replace_tags(cfg.get('title', ''))
            desc_val = replace_tags(cfg.get('description', ''))
            e = discord.Embed(title=title_val, description=desc_val, color=embed_color)
            
            if cfg.get('title_url'): e.url = fix_url(cfg['title_url'])
            
            author_name = replace_tags(cfg.get('author', ''))
            if author_name:
                e.set_author(name=author_name, url=fix_url(cfg.get('author_url', '')))
                
            img_url = cfg.get('image_url')
            if cfg.get('has_frame') and img_url:
                res = await generate_framed_image(img_url, color=embed_color)
                if res:
                    img_data, ext = res
                    fname = f"embed_img.{ext}"
                    files.append(discord.File(img_data, filename=fname))
                    e.set_image(url=f"attachment://{fname}")
                else: e.set_image(url=fix_url(img_url))
            elif img_url: e.set_image(url=fix_url(img_url))
            
            if cfg.get('thumbnail_url'): e.set_thumbnail(url=fix_url(cfg['thumbnail_url']))
            if cfg.get('footer'): e.set_footer(text=replace_tags(cfg['footer']))
            if cfg.get('timestamp'): e.timestamp = datetime.datetime.now()
            embeds.append(e)

        content_val = replace_tags(cfg.get('outer_text')) if cfg.get('outer_text', '').strip() else None
        msg = None
        
        # Próba edycji starej wiadomości (jeśli to nie test)
        if not is_test and cfg.get('last_message_id'):
            try:
                old_msg = await channel.fetch_message(int(cfg['last_message_id']))
                await old_msg.edit(content=content_val, embeds=embeds, attachments=files)
                msg = old_msg
            except: pass

        if not msg:
            msg = await channel.send(content=content_val, embeds=embeds, files=files)
            if not is_test:
                try:
                    conn = sqlite3.connect(DB_NAME)
                    conn.cursor().execute("UPDATE embed_configs SET last_message_id = ? WHERE id = ?", (str(msg.id), config_id))
                    conn.commit(); conn.close()
                except: pass
                
        if cfg.get('category') == 'rules' and cfg.get('reaction_emoji'):
            try: await msg.add_reaction(cfg['reaction_emoji'])
            except: pass

        return {'success': True}

async def setup(bot):
    await bot.add_cog(Embeds(bot))
