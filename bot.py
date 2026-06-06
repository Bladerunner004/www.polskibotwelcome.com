import sys
import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import os
import json
import glob
from aiohttp import web
from dotenv import load_dotenv
import math

# Ustawienie kodowania dla Windows
if sys.platform == 'win32':
    import io
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--guild', type=str, default=None)
args, unknown = parser.parse_known_args()

# Konfiguracja ścieżek
STATUS_FILE_PATH = "bot_status.json"
SYNC_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
IS_CUSTOM_BOT = False
GUILD_ID = None

from database import get_prefix, get_settings, DB_NAME, get_custom_bot, update_custom_bot_status

if args.guild:
    GUILD_ID = args.guild
    c_bot = get_custom_bot(GUILD_ID)
    if c_bot and c_bot.get('token'):
        TOKEN = c_bot['token']
        IS_CUSTOM_BOT = True
        STATUS_FILE_PATH = f"bot_status_custom_{GUILD_ID}.json"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

def get_dynamic_prefix(bot, message):
    if not message.guild: return "!"
    return get_prefix(str(message.guild.id))

class PolskiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_dynamic_prefix, intents=intents)
        self.initial_extensions = [
            'cogs.embeds',
            'cogs.welcome',
            'cogs.counters',
            'cogs.media_radar',
            'cogs.selfrole',
            'cogs.moderation',
            'cogs.tickets',
            'cogs.levels',
            'cogs.fun',
            'cogs.general',
            'cogs.autorole',
            'cogs.music'
        ]

    async def setup_hook(self):
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ Załadowano moduł: {ext}")
            except Exception as e:
                print(f"❌ Błąd ładowania {ext}: {e}")
        
        if not IS_CUSTOM_BOT:
            asyncio.create_task(self.run_internal_api())
        self.update_status_file.start()

    @tasks.loop(seconds=5)
    async def update_status_file(self):
        """Zapisuje status i obsługuje synchronizację plików z dashboardu."""
        try:
            latency = 0
            if self.latency and not math.isnan(self.latency):
                latency = round(self.latency * 1000)
            
            is_online = self.is_ready() and not self.is_closed()
            if IS_CUSTOM_BOT:
                update_custom_bot_status(GUILD_ID, "online" if is_online else "offline")
            else:
                status = {
                    "latency": latency,
                    "last_seen": datetime.datetime.now().timestamp(),
                    "status": "online" if is_online else "offline"
                }
                with open(STATUS_FILE_PATH, "w") as f: json.dump(status, f)
            
            # Obsługa plików synchronizacji
            for sf in glob.glob(os.path.join(SYNC_DIR, "sync_needed_*.json")):
                try:
                    with open(sf, "r") as f: data = json.load(f)
                    guild = self.get_guild(int(os.path.basename(sf).split('_')[2]))
                    if guild:
                        endpoint = data.get('endpoint', '')
                        payload = data.get('data', {})
                        
                        # Przekazywanie zadań do odpowiednich modułów
                        if "sync_counters" in endpoint:
                            cog = self.get_cog('Counters')
                            if cog: await cog.update_all_counters(guild)
                        elif "sync_boosters" in endpoint:
                            cog = self.get_cog('AutoRole')
                            if cog: await cog.sync_boosters(guild)
                        elif "send_embed" in endpoint or "test_embed" in endpoint:
                            cog = self.get_cog('Embeds')
                            if cog:
                                data_to_process = payload or {}
                                if "test_embed" in endpoint:
                                    data_to_process['is_test'] = True
                                await cog.do_process_embed_logic(data_to_process)
                        elif "send_selfrole" in endpoint or "test_selfrole" in endpoint:
                            cog = self.get_cog('SelfRole')
                            if cog: 
                                from database import get_selfrole_configs
                                configs = get_selfrole_configs(guild.id)
                                cfg = next((c for c in configs if str(c['id']) == str(payload.get('config_id'))), None)
                                if cfg:
                                    ch = guild.get_channel(int(cfg['channel_id']))
                                    is_test = "test_selfrole" in endpoint or payload.get('is_test', False)
                                    await cog.send_selfrole_panel(ch, cfg, is_test=is_test)
                        elif "test_welcome" in endpoint or "welcome" in endpoint:
                            cog = self.get_cog('Welcome')
                            if cog:
                                member = guild.owner or guild.me or (guild.members[0] if guild.members else None)
                                if not member:
                                    try: member = await guild.fetch_member(guild.owner_id)
                                    except: member = guild.me
                                if member:
                                    await cog.send_welcome_message(
                                        guild,
                                        member,
                                        payload.get('type', 'powitanie'),
                                        target_id=payload.get('config_id'),
                                        is_test=True
                                    )
                    os.remove(sf)
                except Exception as e: print(f"⚠️ [SYNC ERROR] {sf}: {e}")
        except: pass

    async def run_internal_api(self):
        app = web.Application()
        app.add_routes([
            web.get('/latency', lambda r: web.json_response({'latency': round(self.latency * 1000)})),
            web.get('/guilds', self.handle_api_get_guilds),
            web.get('/guilds/{guild_id}/channels', self.handle_api_guild_channels),
            web.get('/guilds/{guild_id}/roles', self.handle_api_guild_roles),
            web.post('/send_embed', self.handle_api_embed),
            web.post('/test_embed', self.handle_api_embed),
            web.post('/send_selfrole', self.handle_api_selfrole),
            web.post('/test_selfrole', self.handle_api_selfrole),
            web.post('/test_welcome', self.handle_api_welcome),
            web.post('/guilds/{guild_id}/sync_boosters', self.handle_api_sync_boosters),
            web.post('/guilds/{guild_id}/sync_counters', self.handle_api_sync_counters),
            web.post('/guilds/{guild_id}/delete_channel/{channel_id}', self.handle_api_delete_channel),
            web.post('/test_media', self.handle_api_test_media),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', 5006).start()

    async def handle_api_get_guilds(self, request):
        try:
            guild_ids = [str(g.id) for g in self.guilds]
            return web.json_response({'guild_ids': guild_ids})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_guild_channels(self, request):
        try:
            guild_id = request.match_info.get('guild_id')
            guild = self.get_guild(int(guild_id))
            if not guild:
                return web.json_response({'error': 'Gildia nieznaleziona'}, status=404)
            channels = []
            for c in guild.channels:
                if c.type.value in (0, 5):
                    channels.append({"id": str(c.id), "name": c.name})
            return web.json_response(channels)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_guild_roles(self, request):
        try:
            guild_id = request.match_info.get('guild_id')
            guild = self.get_guild(int(guild_id))
            if not guild:
                return web.json_response({'error': 'Gildia nieznaleziona'}, status=404)
            roles = []
            for r in guild.roles:
                if r.name != "@everyone" and not r.managed:
                    color_int = r.color.value
                    color_hex = f"#{color_int:06x}" if color_int != 0 else "#b5bac1"
                    roles.append({"id": str(r.id), "name": r.name, "color": color_hex})
            return web.json_response(roles)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_embed(self, request):
        data = await request.json()
        if "test" in request.path: data['is_test'] = True
        cog = self.get_cog('Embeds')
        if cog:
            res = await cog.do_process_embed_logic(data)
            return web.json_response(res)
        return web.json_response({'success': False, 'error': 'Moduł Embeds niezaładowany'})

    async def handle_api_selfrole(self, request):
        data = await request.json()
        if "test" in request.path: data['is_test'] = True
        cog = self.get_cog('SelfRole')
        if cog:
            from database import get_selfrole_configs
            configs = get_selfrole_configs(data.get('guild_id'))
            cfg = next((c for c in configs if str(c['id']) == str(data.get('config_id'))), None)
            if cfg:
                guild = self.get_guild(int(data.get('guild_id')))
                channel = guild.get_channel(int(cfg['channel_id']))
                await cog.send_selfrole_panel(channel, cfg, is_test=data.get('is_test', False))
                return web.json_response({'success': True})
            return web.json_response({'success': False, 'error': 'Konfiguracja nieznaleziona'})
        return web.json_response({'success': False, 'error': 'Moduł SelfRole niezaładowany'})

    async def handle_api_welcome(self, request):
        try:
            data = await request.json()
            guild_id = data.get('guild_id')
            config_id = data.get('config_id')
            config_type = data.get('type', 'powitanie')
            
            guild = self.get_guild(int(guild_id))
            if guild:
                cog = self.get_cog('Welcome')
                if cog:
                    member = guild.owner or guild.me or (guild.members[0] if guild.members else None)
                    if not member:
                        try: member = await guild.fetch_member(guild.owner_id)
                        except: member = guild.me
                    if member:
                        await cog.send_welcome_message(guild, member, config_type, target_id=config_id, is_test=True)
                        return web.json_response({'success': True})
            return web.json_response({'success': False, 'error': 'Gildia lub moduł Welcome nieznalezione'})
        except Exception as e:
            return web.json_response({'success': False, 'error': str(e)})

    async def handle_api_sync_boosters(self, request):
        try:
            guild_id = request.match_info.get('guild_id')
            guild = self.get_guild(int(guild_id))
            if guild:
                cog = self.get_cog('AutoRole')
                if cog:
                    await cog.sync_boosters(guild)
                    return web.json_response({'success': True})
            return web.json_response({'success': False, 'error': 'Gildia lub moduł AutoRole nieznalezione'})
        except Exception as e:
            return web.json_response({'success': False, 'error': str(e)})

    async def handle_api_sync_counters(self, request):
        try:
            guild_id = request.match_info.get('guild_id')
            guild = self.get_guild(int(guild_id))
            if guild:
                cog = self.get_cog('Counters')
                if cog:
                    await cog.update_all_counters(guild)
                    return web.json_response({'success': True})
            return web.json_response({'success': False, 'error': 'Gildia lub moduł Counters nieznalezione'})
        except Exception as e:
            return web.json_response({'success': False, 'error': str(e)})

    async def handle_api_delete_channel(self, request):
        try:
            guild_id = request.match_info.get('guild_id')
            channel_id = request.match_info.get('channel_id')
            guild = self.get_guild(int(guild_id))
            if guild:
                channel = guild.get_channel(int(channel_id))
                if channel:
                    await channel.delete()
                    return web.json_response({'success': True})
                else:
                    return web.json_response({'success': True, 'warning': 'Channel not found on Discord'})
            return web.json_response({'success': False, 'error': 'Gildia nieznaleziona'})
        except Exception as e:
            return web.json_response({'success': False, 'error': str(e)})

    async def handle_api_test_media(self, request):
        try:
            data = await request.json()
            guild_id = data.get('guild_id')
            config_id = data.get('config_id')
            
            guild = self.get_guild(int(guild_id))
            if guild:
                cog = self.get_cog('MediaRadar')
                if cog:
                    from database import get_media_configs
                    configs = get_media_configs(guild.id)
                    cfg = next((c for c in configs if str(c['id']) == str(config_id)), None)
                    if cfg:
                        account = cfg.get('account_id', 'test_user')
                        platform = cfg.get('platform', 'youtube')
                        title = "Testowe powiadomienie z panelu PolskiBot!"
                        url = f"https://{platform}.com"
                        thumb = "https://cdn.discordapp.com/embed/avatars/0.png"
                        await cog.send_notification(guild, cfg, title, url, thumb, account, platform)
                        return web.json_response({'success': True})
                    return web.json_response({'success': False, 'error': 'Konfiguracja nieznaleziona w bazie'})
            return web.json_response({'success': False, 'error': 'Gildia lub moduł MediaRadar nieznalezione'})
        except Exception as e:
            return web.json_response({'success': False, 'error': str(e)})

bot = PolskiBot()

@bot.check
async def check_commands_channel(ctx):
    if not ctx.guild:
        return True
    if ctx.author.guild_permissions.manage_guild:
        return True
    
    settings = get_settings(str(ctx.guild.id))
    cmd_channel_id = settings.get("commands_channel_id")
    if cmd_channel_id and str(cmd_channel_id).isdigit():
        if ctx.channel.id != int(cmd_channel_id):
            await ctx.send(f"❌ Komendy na tym serwerze są dozwolone tylko na kanale <#{cmd_channel_id}>!", ephemeral=True)
            return False
    return True

@bot.event
async def on_ready():
    print(f"🚀 PolskiBot (Modularny) zalogowany jako {bot.user}")
    if IS_CUSTOM_BOT:
        print(f"[CUSTOM BOT] Zalogowano dla gildii {GUILD_ID}")
        update_custom_bot_status(GUILD_ID, "online")
    else:
        try:
            print("[SYSTEM] Synchronizuję komendy (hybrid/slash) globalnie z Discordem...")
            synced = await bot.tree.sync()
            print(f"✅ Zsynchronizowano pomyślnie {len(synced)} komend globalnie!")
        except Exception as e:
            print(f"❌ Błąd synchronizacji komend: {e}")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))