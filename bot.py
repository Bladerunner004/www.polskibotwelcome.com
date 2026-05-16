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
            'cogs.general'
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
                        elif "send_embed" in endpoint:
                            cog = self.get_cog('Embeds')
                            if cog: await cog.do_process_embed_logic(payload)
                        elif "send_selfrole" in endpoint:
                            cog = self.get_cog('SelfRole')
                            if cog: 
                                from database import get_selfrole_configs
                                configs = get_selfrole_configs(guild.id)
                                cfg = next((c for c in configs if str(c['id']) == str(payload.get('config_id'))), None)
                                if cfg:
                                    ch = guild.get_channel(int(cfg['channel_id']))
                                    await cog.send_selfrole_panel(ch, cfg, is_test=payload.get('is_test', False))
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

bot = PolskiBot()

@bot.event
async def on_ready():
    print(f"🚀 PolskiBot (Modularny) zalogowany jako {bot.user}")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))