import discord
from discord.ext import commands, tasks
import aiohttp
import os
import datetime

class MediaRadar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.live_status_memory = {}
        self.check_media_streams.start()

    def cog_unload(self):
        self.check_media_streams.cancel()

    @tasks.loop(minutes=5)
    async def check_media_streams(self):
        """Pętla sprawdzająca statusy kanałów na YT, Twitch, Kick i TikTok."""
        YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
        TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
        TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
        
        twitch_token = None
        if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            twitch_token = data.get('access_token')
            except: pass

        from database import get_media_configs, get_settings
        for guild in self.bot.guilds:
            configs = get_media_configs(guild.id)
            for cfg in configs:
                if not cfg.get('enabled') or not cfg.get('account_id'): continue
                
                platform = cfg['platform'].lower()
                account = cfg['account_id'].strip().replace('@', '')
                memory_key = f"{guild.id}_{platform}_{account}"
                
                is_live = False
                stream_url, stream_title, stream_thumb = "", "", ""
                
                try:
                    async with aiohttp.ClientSession() as session:
                        # Logika dla TWITCH
                        if platform == "twitch" and twitch_token:
                            headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {twitch_token}"}
                            async with session.get(f"https://api.twitch.tv/helix/streams?user_login={account}", headers=headers) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get('data'):
                                        s = data['data'][0]
                                        is_live = True
                                        stream_url = f"https://twitch.tv/{account}"
                                        stream_title = s.get('title', "Live!")
                                        stream_thumb = s.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')

                        # Logika dla YOUTUBE
                        elif platform == "youtube" and YOUTUBE_API_KEY:
                            async with session.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={account}&maxResults=1&order=date&type=video&key={YOUTUBE_API_KEY}") as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get('items'):
                                        v = data['items'][0]
                                        vid_id = v['id']['videoId']
                                        if self.live_status_memory.get(memory_key) != vid_id:
                                            is_live = True
                                            stream_url = f"https://youtube.com/watch?v={vid_id}"
                                            stream_title = v['snippet']['title']
                                            stream_thumb = v['snippet']['thumbnails']['high']['url']
                                            self.live_status_memory[memory_key] = vid_id

                        # Logika dla KICK (Atrapa API)
                        elif platform == "kick":
                            async with session.get(f"https://kick.com/api/v1/channels/{account}") as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get('livestream'):
                                        is_live = True
                                        stream_url = f"https://kick.com/{account}"
                                        stream_title = data['livestream'].get('session_title')
                                        stream_thumb = data['livestream'].get('thumbnail', {}).get('url')

                except Exception as e:
                    print(f"⚠️ [MEDIA_RADAR] Błąd dla {account}: {e}")

                # Wysyłanie powiadomienia
                if is_live and (platform == 'youtube' or self.live_status_memory.get(memory_key) != True):
                    if platform != 'youtube': self.live_status_memory[memory_key] = True
                    await self.send_notification(guild, cfg, stream_title, stream_url, stream_thumb, account, platform)
                elif not is_live:
                    self.live_status_memory[memory_key] = False

    async def send_notification(self, guild, cfg, title, url, thumb, account, platform):
        channel = guild.get_channel(int(cfg['discord_channel_id']))
        if not channel: return
        
        brand_colors = {"youtube": 0xFF0000, "twitch": 0x9146FF, "kick": 0x53FC18, "tiktok": 0x000000}
        color = brand_colors.get(platform, 0x74b816)
        
        embed = discord.Embed(title=title, url=url, color=color, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{account} na {platform.upper()}", url=url)
        if thumb: embed.set_image(url=thumb)
        embed.description = f"🚀 **{account}** właśnie nadaje!\n\n🔗 **Kliknij tutaj:**\n{url}"
        
        msg_text = cfg.get('message', '').replace('{account}', f"**{account}**")
        await channel.send(content=msg_text, embed=embed)

async def setup(bot):
    await bot.add_cog(MediaRadar(bot))
