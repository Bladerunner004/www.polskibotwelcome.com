import discord
from discord.ext import commands
import sqlite3
import json
from database import DB_NAME, get_settings, get_member_roles, save_member_roles

class AutoRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        settings = get_settings(str(guild.id))
        
        # 1. Sprawdzenie typu (Bot / Człowiek) i nadanie odpowiednich ról
        if member.bot:
            bot_roles_ids = settings.get('autorole_bot_roles', [])
            for r_id in bot_roles_ids:
                role = guild.get_role(int(r_id))
                if role:
                    try: await member.add_roles(role)
                    except Exception as e: print(f"⚠️ [AUTOROLE] Nie można nadać roli bota: {role.name} ({e})")
        else:
            # Użytkownik (Human)
            # A. Nadanie domyślnych ról dla ludzi
            human_roles_ids = settings.get('autorole_human_roles', [])
            for r_id in human_roles_ids:
                role = guild.get_role(int(r_id))
                if role:
                    try: await member.add_roles(role)
                    except Exception as e: print(f"⚠️ [AUTOROLE] Nie można nadać roli użytkownika: {role.name} ({e})")
            
            # B. Jeśli tryb to przywracanie ról (restore)
            mode = settings.get('autorole_mode', 'disabled')
            if mode == 'restore':
                saved_role_ids = get_member_roles(str(guild.id), str(member.id))
                for r_id in saved_role_ids:
                    role = guild.get_role(int(r_id))
                    # Nie nadajemy ról zarządzanych przez integracje ani default_role
                    if role and not role.managed and role != guild.default_role:
                        try: await member.add_roles(role)
                        except Exception as e: print(f"⚠️ [AUTOROLE] Nie można przywrócić roli {role.name} ({e})")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Zapisujemy obecne role użytkownika przed wyjściem w celu ewentualnego przywrócenia (restore)
        if not member.bot:
            guild = member.guild
            roles_to_save = [str(role.id) for role in member.roles if role != guild.default_role and not role.managed]
            try:
                save_member_roles(str(guild.id), str(member.id), roles_to_save)
                print(f"💾 [AUTOROLE] Zapisano role dla {member} na serwerze {guild.name}")
            except Exception as e:
                print(f"⚠️ [AUTOROLE] Błąd zapisu ról dla {member}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Sprawdzanie czy użytkownik zaczął lub przestał boostować
        guild = after.guild
        settings = get_settings(str(guild.id))
        booster_roles_ids = settings.get('autorole_booster_roles', [])
        if not booster_roles_ids: return

        was_boosting = before.premium_since is not None
        is_boosting = after.premium_since is not None

        if not was_boosting and is_boosting:
            # Zaczął boostować - dajemy role boosterów
            for r_id in booster_roles_ids:
                role = guild.get_role(int(r_id))
                if role:
                    try: 
                        await after.add_roles(role)
                        print(f"💎 [AUTOROLE] Użytkownik {after} zaczął boostować. Nadano rolę {role.name}.")
                    except Exception as e: 
                        print(f"⚠️ [AUTOROLE] Nie można nadać roli boostera: {role.name} ({e})")

        elif was_boosting and not is_boosting:
            # Przestał boostować - zabieramy role boosterów, jeśli opcja usuwania jest włączona
            should_remove = settings.get('autorole_booster_remove', True)
            if should_remove:
                for r_id in booster_roles_ids:
                    role = guild.get_role(int(r_id))
                    if role and role in after.roles:
                        try:
                            await after.remove_roles(role)
                            print(f"❌ [AUTOROLE] Użytkownik {after} przestał boostować. Odebrano rolę {role.name}.")
                        except Exception as e:
                            print(f"⚠️ [AUTOROLE] Nie można odebrać roli boostera: {role.name} ({e})")

    async def sync_boosters(self, guild):
        """Przeszukuje wszystkich członków serwera i aktualizuje im role boostera."""
        settings = get_settings(str(guild.id))
        booster_roles_ids = settings.get('autorole_booster_roles', [])
        should_remove = settings.get('autorole_booster_remove', True)
        
        if not booster_roles_ids: return

        # Pobieramy role discord.Role
        booster_roles = []
        for r_id in booster_roles_ids:
            role = guild.get_role(int(r_id))
            if role: booster_roles.append(role)

        if not booster_roles: return

        print(f"🔄 [AUTOROLE] Rozpoczęto synchronizację boosterów dla serwera {guild.name}")
        for member in guild.members:
            is_boosting = member.premium_since is not None
            
            if is_boosting:
                # Powinien mieć role
                for role in booster_roles:
                    if role not in member.roles:
                        try: 
                            await member.add_roles(role)
                            print(f"💎 [AUTOROLE] Synchronizacja: Nadano rolę {role.name} dla {member}")
                        except: pass
            else:
                # Nie boostuje - sprawdzamy czy odebrać role
                if should_remove:
                    for role in booster_roles:
                        if role in member.roles:
                            try:
                                await member.remove_roles(role)
                                print(f"❌ [AUTOROLE] Synchronizacja: Odebrano rolę {role.name} dla {member}")
                            except: pass

async def setup(bot):
    await bot.add_cog(AutoRole(bot))
