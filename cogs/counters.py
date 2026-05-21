import discord
from discord.ext import commands, tasks
import asyncio
import sqlite3
from database import DB_NAME

class Counters(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.counter_locks = {}
        self.update_counters_loop.start()

    def cog_unload(self):
        self.update_counters_loop.cancel()

    @tasks.loop(minutes=10)
    async def update_counters_loop(self):
        """Okresowa aktualizacja wszystkich liczników na wszystkich serwerach."""
        for guild in self.bot.guilds:
            try: await self.update_all_counters(guild)
            except: pass

    async def update_all_counters(self, guild):
        if not guild: return
        guild_id = str(guild.id)
        
        if guild_id not in self.counter_locks:
            self.counter_locks[guild_id] = asyncio.Lock()
        
        async with self.counter_locks[guild_id]:
            from database import get_settings, update_counter_channel_id, get_role_counters, update_role_counter_channel_id
            settings = get_settings(guild_id)
            
            # --- 1. LICZNIKI SYSTEMOWE (HUMANS, BOTS, BANS) ---
            async def process_stat(type_key, enabled, name_format, current_id, pos):
                if not enabled:
                    if current_id and str(current_id).strip() != "None":
                        ch = guild.get_channel(int(current_id))
                        if ch: 
                            try: await ch.delete(); print(f"🗑️ [COUNTERS] Usunięto kanał {type_key}")
                            except: pass
                        update_counter_channel_id(guild.id, type_key, None)
                    return

                count = 0
                if type_key == "humans": count = sum(1 for m in guild.members if not m.bot)
                elif type_key == "bots": count = sum(1 for m in guild.members if m.bot)
                elif type_key == "bans":
                    try:
                        ban_count = 0
                        async for _ in guild.bans(limit=1000): ban_count += 1
                        count = ban_count
                    except: pass
                
                new_name = name_format.replace("{count}", str(count))
                channel = guild.get_channel(int(current_id)) if current_id and str(current_id).isdigit() else None
                
                if not channel:
                    try:
                        channel = await guild.create_voice_channel(
                            name=new_name,
                            overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)},
                            position=pos
                        )
                        update_counter_channel_id(guild.id, type_key, channel.id)
                    except: pass
                elif channel.name != new_name:
                    try: await channel.edit(name=new_name)
                    except: pass

            await process_stat("humans", settings.get("counter_humans_enabled"), settings.get("counter_humans_name", "Humans: {count}"), settings.get("counter_humans_channel_id"), 0)
            await process_stat("bots", settings.get("counter_bots_enabled"), settings.get("counter_bots_name", "Bots: {count}"), settings.get("counter_bots_channel_id"), 1)
            await process_stat("bans", settings.get("counter_bans_enabled"), settings.get("counter_bans_name", "Bans: {count}"), settings.get("counter_bans_channel_id"), 2)

            # --- 1a. LICZNIK TOP LEVEL (Zintegrowany z XP) ---
            if settings.get("counter_toplevel_enabled"):
                try:
                    conn = sqlite3.connect(DB_NAME)
                    c = conn.cursor()
                    c.execute("SELECT MAX(level) FROM user_levels WHERE guild_id = ?", (guild_id,))
                    max_lvl = c.fetchone()[0] or 0
                    conn.close()
                    
                    name_format = settings.get("counter_toplevel_name", "Top Level: {count}")
                    new_name = name_format.replace("{count}", str(max_lvl))
                    ch_id = settings.get("counter_toplevel_channel_id")
                    channel = guild.get_channel(int(ch_id)) if ch_id and str(ch_id).isdigit() else None
                    
                    if not channel:
                        channel = await guild.create_voice_channel(name=new_name, overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)})
                        update_counter_channel_id(guild.id, "toplevel", channel.id)
                    elif channel.name != new_name:
                        await channel.edit(name=new_name)
                except: pass

            # --- 2. DYNAMICZNE LICZNIKI RÓL ---
            role_configs = get_role_counters(guild.id)
            for cfg in role_configs:
                is_enabled = cfg.get('enabled', 1)
                ch_id = cfg.get('channel_id')
                
                if is_enabled:
                    count = 0
                    r_ids = [int(rid) for rid in cfg['roles']]
                    if cfg['mode'] == 'white':
                        m_ids = set()
                        for rid in r_ids:
                            r = guild.get_role(rid)
                            if r: 
                                for m in r.members: m_ids.add(m.id)
                        count = len(m_ids)
                    else:
                        blacklisted = set()
                        for rid in r_ids:
                            r = guild.get_role(rid)
                            if r:
                                for m in r.members: blacklisted.add(m.id)
                        all_h = sum(1 for m in guild.members if not m.bot)
                        count = max(0, all_h - len(blacklisted))

                    new_name = (cfg['name'] or "Role: {count}").replace("{count}", str(count))
                    ch = guild.get_channel(int(ch_id)) if ch_id and str(ch_id).isdigit() else None
                    
                    if not ch:
                        try:
                            ch = await guild.create_voice_channel(name=new_name, overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)})
                            update_role_counter_channel_id(cfg['id'], ch.id)
                        except: pass
                    elif ch.name != new_name:
                        try: await ch.edit(name=new_name)
                        except: pass
                elif ch_id:
                    ch = guild.get_channel(int(ch_id))
                    if ch: 
                        try: await ch.delete()
                        except: pass
                    update_role_counter_channel_id(cfg['id'], None)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.update_all_counters(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.update_all_counters(member.guild)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Aktualizacja liczników gdy zmienią się role użytkownika."""
        if before.roles != after.roles:
            await self.update_all_counters(after.guild)

async def setup(bot):
    await bot.add_cog(Counters(bot))
