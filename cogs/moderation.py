import discord
from discord.ext import commands
import datetime
import json
import re
import asyncio
from database import get_settings, add_audit_log, log_message_activity, log_join_activity, add_warning, get_warnings, clear_warnings
from badwords_list import GLOBAL_BADWORDS

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam_control = {} # {user_id: [timestamps]}

    async def send_log(self, guild, category, embed):
        settings = get_settings(str(guild.id))
        ch_id = settings.get('logs_channel_id')
        if not ch_id or not settings.get(f"logs_{category}", False): return
        channel = guild.get_channel(int(ch_id))
        if channel: await channel.send(embed=embed)

    async def do_confirm(self, ctx, text):
        settings = get_settings(str(ctx.guild.id))
        confirm = settings.get('moderation_confirm', False)
        await ctx.send(text, ephemeral=not confirm)

    @commands.hybrid_command(name="ban", description="Zbanuj użytkownika.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.ban(uzytkownik, reason=powod)
        await self.do_confirm(ctx, f"🔨 Zbanowano {uzytkownik.mention}. Powód: {powod}")
        add_audit_log(ctx.guild.id, "Moderacja", ctx.author.name, ctx.author.id, "BAN", f"Zbanowano {uzytkownik.name} ({uzytkownik.id})")

    @commands.hybrid_command(name="unban", description="Odbanuj użytkownika.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, uzytkownik_id: str):
        try:
            user = await self.bot.fetch_user(int(uzytkownik_id))
            await ctx.guild.unban(user)
            await self.do_confirm(ctx, f"✅ Odbanowano użytkownika o ID {uzytkownik_id}.")
        except:
            await ctx.send("❌ Nie znaleziono użytkownika o podanym ID.", ephemeral=True)

    @commands.hybrid_command(name="kick", description="Wyrzuć użytkownika.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        await ctx.guild.kick(uzytkownik, reason=powod)
        await self.do_confirm(ctx, f"👢 Wyrzucono {uzytkownik.mention}. Powód: {powod}")

    @commands.hybrid_command(name="mute", description="Wycisz użytkownika (Timeout).")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, uzytkownik: discord.Member, minuty: int, *, powod: str = "Brak"):
        duration = datetime.timedelta(minutes=minuty)
        await uzytkownik.timeout(duration, reason=powod)
        await self.do_confirm(ctx, f"🔇 Wyciszono {uzytkownik.mention} na {minuty} min. Powód: {powod}")

    @commands.hybrid_command(name="unmute", description="Zdejmij wyciszenie.")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, uzytkownik: discord.Member):
        await uzytkownik.timeout(None)
        await self.do_confirm(ctx, f"🔊 Zdjęto wyciszenie z {uzytkownik.mention}.")

    @commands.hybrid_command(name="warn", description="Nadaj ostrzeżenie użytkownikowi.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, uzytkownik: discord.Member, *, powod: str = "Brak"):
        add_warning(ctx.guild.id, uzytkownik.id, ctx.author.id, powod)
        await self.do_confirm(ctx, f"⚠️ Nadano ostrzeżenie dla {uzytkownik.mention}. Powód: {powod}")

    @commands.hybrid_command(name="warns", description="Sprawdź ostrzeżenia użytkownika.")
    async def warns(self, ctx, uzytkownik: discord.Member):
        warnings = get_warnings(ctx.guild.id, uzytkownik.id)
        if not warnings:
            return await ctx.send(f"✅ {uzytkownik.mention} nie ma żadnych ostrzeżeń.", ephemeral=True)
        
        embed = discord.Embed(title=f"Ostrzeżenia: {uzytkownik.name}", color=0xffa500)
        for i, w in enumerate(warnings, 1):
            embed.add_field(name=f"#{i} | Moderator: {w['moderator_id']}", value=f"Powód: {w['reason']}\nData: {w['timestamp']}", inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="clear", description="Usuń określoną liczbę wiadomości.")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, ilosc: int):
        await ctx.channel.purge(limit=ilosc + 1)
        await ctx.send(f"🧹 Usunięto {ilosc} wiadomości.", delete_after=5)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return
        settings = get_settings(str(message.guild.id))
        
        # Ignoruj administrację w AutoModzie
        if message.author.guild_permissions.manage_messages:
            log_message_activity(message.guild.id, message.channel.id)
            return

        is_violating = False
        violation_reason = ""

        # 1. Antylink
        if settings.get("automod_antilink"):
            if re.search(r'(https?://|www\.)[^\s]+', message.content):
                is_violating = True
                violation_reason = "Linki są niedozwolone!"

        # 2. Anticaps
        if not is_violating and settings.get("automod_anticaps"):
            if len(message.content) > 10 and sum(1 for c in message.content if c.isupper()) / len(message.content) > 0.7:
                is_violating = True
                violation_reason = "Nie krzycz! (Zbyt dużo dużych liter)"

        # 3. Antispam
        if not is_violating and settings.get("automod_antispam"):
            uid = message.author.id
            now = datetime.datetime.now().timestamp()
            if uid not in self.spam_control: self.spam_control[uid] = []
            self.spam_control[uid] = [t for t in self.spam_control[uid] if now - t < 5]
            self.spam_control[uid].append(now)
            if len(self.spam_control[uid]) > 5:
                is_violating = True
                violation_reason = "Przestań spamować!"

        # 4. Badwords
        if not is_violating and settings.get("automod_badwords"):
            custom_list = settings.get("automod_badwords_list", [])
            all_bad = GLOBAL_BADWORDS + custom_list
            if any(word.lower() in message.content.lower() for word in all_bad):
                is_violating = True
                violation_reason = "Twoja wiadomość zawierała niedozwolone słowa!"

        if is_violating:
            try:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention}, {violation_reason}", delete_after=5)
            except: pass
            return

        # Logowanie aktywności (statystyki)
        log_message_activity(message.guild.id, message.channel.id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        moderator_name = "System/Nieznany"
        moderator_id = "0"
        reason = "Brak powodu"
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    if entry.reason:
                        reason = entry.reason
                    break
        except Exception as e:
            print(f"Błąd odczytu audit log (ban): {e}")

        add_audit_log(guild.id, "mod_actions", moderator_name, moderator_id, "BAN", f"Zbanowano użytkownika {user.name} ({user.id}). Powód: {reason}")

        embed = discord.Embed(
            title="🔨 Użytkownik zbanowany",
            description=f"**Użytkownik:** {user.mention} ({user.name})\n**ID:** {user.id}\n**Moderator:** <@{moderator_id}>\n**Powód:** {reason}",
            color=0xff4757,
            timestamp=datetime.datetime.now()
        )
        if hasattr(user, "display_avatar") and user.display_avatar:
            embed.set_thumbnail(url=user.display_avatar.url)
        await self.send_log(guild, "mod_actions", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        moderator_name = "System/Nieznany"
        moderator_id = "0"
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    break
        except Exception as e:
            print(f"Błąd odczytu audit log (unban): {e}")

        add_audit_log(guild.id, "mod_actions", moderator_name, moderator_id, "UNBAN", f"Odbanowano użytkownika {user.name} ({user.id})")

        embed = discord.Embed(
            title="✅ Użytkownik odbanowany",
            description=f"**Użytkownik:** {user.name} ({user.id})\n**Moderator:** <@{moderator_id}>",
            color=0x2ed573,
            timestamp=datetime.datetime.now()
        )
        await self.send_log(guild, "mod_actions", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        moderator_name = "System/Nieznany"
        moderator_id = "0"
        reason = "Brak powodu"
        is_kick = False
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id and (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds() < 10:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    if entry.reason:
                        reason = entry.reason
                    is_kick = True
                    break
        except Exception as e:
            print(f"Błąd odczytu audit log (kick): {e}")

        if is_kick:
            add_audit_log(guild.id, "mod_actions", moderator_name, moderator_id, "KICK", f"Wyrzucono użytkownika {member.name} ({member.id}). Powód: {reason}")
            embed = discord.Embed(
                title="👢 Użytkownik wyrzucony",
                description=f"**Użytkownik:** {member.mention} ({member.name})\n**ID:** {member.id}\n**Moderator:** <@{moderator_id}>\n**Powód:** {reason}",
                color=0xffa500,
                timestamp=datetime.datetime.now()
            )
            if hasattr(member, "display_avatar") and member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            await self.send_log(guild, "mod_actions", embed)
        else:
            add_audit_log(guild.id, "join_leave", member.name, member.id, "LEAVE", f"Użytkownik {member.name} ({member.id}) opuścił serwer.")
            embed = discord.Embed(
                title="📤 Użytkownik opuścił serwer",
                description=f"**Użytkownik:** {member.mention} ({member.name})\n**ID:** {member.id}",
                color=0xff4757,
                timestamp=datetime.datetime.now()
            )
            if hasattr(member, "display_avatar") and member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            await self.send_log(guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        log_join_activity(guild.id)
        
        add_audit_log(guild.id, "join_leave", member.name, member.id, "JOIN", f"Użytkownik {member.name} ({member.id}) dołączył do serwera.")
        
        embed = discord.Embed(
            title="📥 Nowy użytkownik dołączył",
            description=f"**Użytkownik:** {member.mention} ({member.name})\n**ID:** {member.id}\n**Data założenia konta:** {member.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
            color=0x2ed573,
            timestamp=datetime.datetime.now()
        )
        if hasattr(member, "display_avatar") and member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        await self.send_log(guild, "join_leave", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        
        if before.roles != after.roles:
            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]
            
            moderator_name = "System/Nieznany"
            moderator_id = "0"
            await asyncio.sleep(1)
            try:
                async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                    if entry.target.id == after.id and (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds() < 10:
                        moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                        moderator_id = str(entry.user.id)
                        break
            except Exception as e:
                print(f"Błąd odczytu audit log (role update): {e}")

            for role in added_roles:
                if role.is_default(): continue
                add_audit_log(guild.id, "role_updates", moderator_name, moderator_id, "ROLE_ADD", f"Dodano rolę <@&{role.id}> użytkownikowi {after.name} ({after.id})")
                embed = discord.Embed(
                    title="🛡️ Dodano rolę",
                    description=f"**Użytkownik:** {after.mention}\n**Rola:** <@&{role.id}>\n**Moderator:** <@{moderator_id}>",
                    color=0x2ed573,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "role_updates", embed)

            for role in removed_roles:
                if role.is_default(): continue
                add_audit_log(guild.id, "role_updates", moderator_name, moderator_id, "ROLE_REMOVE", f"Odebrano rolę <@&{role.id}> użytkownikowi {after.name} ({after.id})")
                embed = discord.Embed(
                    title="🛡️ Odebrano rolę",
                    description=f"**Użytkownik:** {after.mention}\n**Rola:** <@&{role.id}>\n**Moderator:** <@{moderator_id}>",
                    color=0xff4757,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "role_updates", embed)

        if before.timed_out != after.timed_out or before.communication_disabled_until != after.communication_disabled_until:
            moderator_name = "System/Nieznany"
            moderator_id = "0"
            reason = "Brak powodu"
            await asyncio.sleep(1)
            try:
                async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                    if entry.target.id == after.id and (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds() < 10:
                        moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                        moderator_id = str(entry.user.id)
                        if entry.reason:
                            reason = entry.reason
                        break
            except Exception as e:
                print(f"Błąd odczytu audit log (member update/timeout): {e}")

            if after.timed_out:
                duration_sec = int((after.communication_disabled_until - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
                duration_min = max(1, int(duration_sec / 60))
                add_audit_log(guild.id, "mod_actions", moderator_name, moderator_id, "MUTE", f"Wyciszono użytkownika {after.name} ({after.id}) na {duration_min} min. Powód: {reason}")
                embed = discord.Embed(
                    title="🔇 Wyciszono użytkownika (Timeout)",
                    description=f"**Użytkownik:** {after.mention} ({after.name})\n**Czas:** {duration_min} min\n**Moderator:** <@{moderator_id}>\n**Powód:** {reason}",
                    color=0xffa500,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "mod_actions", embed)
            else:
                add_audit_log(guild.id, "mod_actions", moderator_name, moderator_id, "UNMUTE", f"Zdjęto wyciszenie z użytkownika {after.name} ({after.id})")
                embed = discord.Embed(
                    title="🔊 Zdjęto wyciszenie (Timeout)",
                    description=f"**Użytkownik:** {after.mention} ({after.name})\n**Moderator:** <@{moderator_id}>",
                    color=0x2ed573,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "mod_actions", embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        moderator_name = "System/Nieznany"
        moderator_id = "0"
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
                if entry.target.id == channel.id:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    break
        except Exception as e:
            print(f"Błąd odczytu audit log (channel create): {e}")

        ch_type = "tekstowy" if isinstance(channel, discord.TextChannel) else "głosowy" if isinstance(channel, discord.VoiceChannel) else "kategorię" if isinstance(channel, discord.CategoryChannel) else "inny"
        add_audit_log(guild.id, "guild_updates", moderator_name, moderator_id, "CHANNEL_CREATE", f"Utworzono kanał {ch_type} <#{channel.id}> ({channel.name})")

        embed = discord.Embed(
            title="➕ Utworzono kanał",
            description=f"**Kanał:** <#{channel.id}> ({channel.name})\n**Typ:** {ch_type}\n**Administrator:** <@{moderator_id}>",
            color=0x2ed573,
            timestamp=datetime.datetime.now()
        )
        await self.send_log(guild, "guild_updates", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        moderator_name = "System/Nieznany"
        moderator_id = "0"
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                if entry.target.id == channel.id:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    break
        except Exception as e:
            print(f"Błąd odczytu audit log (channel delete): {e}")

        ch_type = "tekstowy" if isinstance(channel, discord.TextChannel) else "głosowy" if isinstance(channel, discord.VoiceChannel) else "kategorię" if isinstance(channel, discord.CategoryChannel) else "inny"
        add_audit_log(guild.id, "guild_updates", moderator_name, moderator_id, "CHANNEL_DELETE", f"Usunięto kanał {ch_type} {channel.name} ({channel.id})")

        embed = discord.Embed(
            title="➖ Usunięto kanał",
            description=f"**Nazwa kanału:** {channel.name}\n**ID:** {channel.id}\n**Typ:** {ch_type}\n**Administrator:** <@{moderator_id}>",
            color=0xff4757,
            timestamp=datetime.datetime.now()
        )
        await self.send_log(guild, "guild_updates", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild: return
        guild = message.guild
        
        moderator_name = "System/Autor"
        moderator_id = str(message.author.id)
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.message_delete):
                if entry.target.id == message.author.id and (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds() < 5:
                    moderator_name = f"{entry.user.name}#{entry.user.discriminator}" if entry.user.discriminator != "0" else entry.user.name
                    moderator_id = str(entry.user.id)
                    break
        except Exception as e:
            pass

        content_snippet = message.content[:200] + "..." if len(message.content) > 200 else message.content
        if not content_snippet: content_snippet = "[Brak treści / Załącznik / Embed]"
        
        add_audit_log(guild.id, "msg_updates", moderator_name, moderator_id, "MESSAGE_DELETE", f"Usunięto wiadomość od {message.author.name} ({message.author.id}) na kanale <#{message.channel.id}>: {content_snippet}")

        embed = discord.Embed(
            title="🗑️ Usunięto wiadomość",
            description=f"**Autor:** {message.author.mention} ({message.author.name})\n**Kanał:** {message.channel.mention}\n**Usunięte przez:** <@{moderator_id}>\n\n**Treść:**\n```\n{content_snippet}\n```",
            color=0xff4757,
            timestamp=datetime.datetime.now()
        )
        await self.send_log(guild, "msg_updates", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild: return
        if before.content == after.content: return
        guild = before.guild
        
        before_snippet = before.content[:200] + "..." if len(before.content) > 200 else before.content
        if not before_snippet: before_snippet = "[Brak treści]"
        after_snippet = after.content[:200] + "..." if len(after.content) > 200 else after.content
        if not after_snippet: after_snippet = "[Brak treści]"

        add_audit_log(guild.id, "msg_updates", before.author.name, before.author.id, "MESSAGE_EDIT", f"Edytowano wiadomość na kanale <#{before.channel.id}>.\nStara: {before_snippet}\nNowa: {after_snippet}")

        embed = discord.Embed(
            title="✏️ Edytowano wiadomość",
            description=f"**Autor:** {before.author.mention} ({before.author.name})\n**Kanał:** {before.channel.mention}\n[Przejdź do wiadomości]({after.jump_url})",
            color=0x00a8fc,
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Przed edycją", value=f"```\n{before_snippet}\n```", inline=False)
        embed.add_field(name="Po edycji", value=f"```\n{after_snippet}\n```", inline=False)
        
        await self.send_log(guild, "msg_updates", embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        
        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                add_audit_log(guild.id, "voice_activity", member.name, member.id, "VOICE_JOIN", f"Użytkownik dołączył do kanału głosowego <#{after.channel.id}> ({after.channel.name})")
                embed = discord.Embed(
                    title="🎙️ Dołączono do kanału głosowego",
                    description=f"**Użytkownik:** {member.mention} ({member.name})\n**Kanał:** {after.channel.mention}",
                    color=0x2ed573,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "voice_activity", embed)
                
            elif before.channel is not None and after.channel is None:
                add_audit_log(guild.id, "voice_activity", member.name, member.id, "VOICE_LEAVE", f"Użytkownik opuścił kanał głosowy {before.channel.name} ({before.channel.id})")
                embed = discord.Embed(
                    title="🎙️ Opuszczono kanał głosowy",
                    description=f"**Użytkownik:** {member.mention} ({member.name})\n**Kanał:** {before.channel.name} ({before.channel.id})",
                    color=0xff4757,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "voice_activity", embed)
                
            elif before.channel is not None and after.channel is not None:
                add_audit_log(guild.id, "voice_activity", member.name, member.id, "VOICE_MOVE", f"Użytkownik przeniósł się z <#{before.channel.id}> do <#{after.channel.id}>")
                embed = discord.Embed(
                    title="🎙️ Przeniesiono kanał głosowy",
                    description=f"**Użytkownik:** {member.mention} ({member.name})\n**Z kanału:** {before.channel.name} ({before.channel.id})\n**Na kanał:** {after.channel.mention}",
                    color=0x00a8fc,
                    timestamp=datetime.datetime.now()
                )
                await self.send_log(guild, "voice_activity", embed)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
