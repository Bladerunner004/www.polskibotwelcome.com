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

# Ustawienie kodowania dla Windows
if sys.platform == 'win32':
    import io
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

# Konfiguracja ścieżek
STATUS_FILE_PATH = "bot_status.json"
SYNC_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

from database import get_prefix, get_settings, DB_NAME

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
            'cogs.autorole'
        ]

    async def setup_hook(self):
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ Załadowano moduł: {ext}")
            except Exception as e:
                print(f"❌ Błąd ładowania {ext}: {e}")
        
        asyncio.create_task(self.run_internal_api())
        self.update_status_file.start()

    @tasks.loop(seconds=5)
    async def update_status_file(self):
        """Zapisuje status i obsługuje synchronizację plików z dashboardu."""
        try:
            status = {"latency": round(self.latency * 1000) if self.latency else 0, "last_seen": datetime.datetime.now().timestamp(), "status": "online"}
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
            web.post('/send_embed', self.handle_api_embed),
            web.post('/test_embed', self.handle_api_embed),
            web.post('/send_selfrole', self.handle_api_selfrole),
            web.post('/test_selfrole', self.handle_api_selfrole),
            web.post('/test_welcome', self.handle_api_welcome),
            web.post('/guilds/{guild_id}/sync_boosters', self.handle_api_sync_boosters),
            web.post('/guilds/{guild_id}/sync_counters', self.handle_api_sync_counters),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', 5006).start()

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

bot = PolskiBot()

@bot.event
async def on_ready():
    print(f"🚀 PolskiBot (Modularny) zalogowany jako {bot.user}")
    try:
        print("[SYSTEM] Synchronizuję komendy (hybrid/slash) globalnie z Discordem...")
        synced = await bot.tree.sync()
        print(f"✅ Zsynchronizowano pomyślnie {len(synced)} komend globalnie!")
    except Exception as e:
        print(f"❌ Błąd synchronizacji komend: {e}")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))