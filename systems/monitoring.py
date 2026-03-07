import asyncio
import logging
import time
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone

from config import CHECK_INTERVAL, BOT_AVATAR_URL, BOT_VERSION
from core.checker import fetch_all, VersionInfo
from core.storage import get_version_data, update_version, get_all_guilds
from core.notifier import build_update_embed, create_language_view
from core.history import fetch_deploy_history

logger = logging.getLogger("BloxPulse.Monitoring")

# Global status tracking for the API service to consume
API_STATUS = {"WindowsPlayer": True, "MacPlayer": True, "AndroidApp": True, "iOS": True}

class MonitoringSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitor_task.start()

    def cog_unload(self):
        self.monitor_task.cancel()

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def monitor_task(self):
        """Background monitoring task."""
        try:
            logger.info("Starting monitoring cycle...")
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, fetch_all)

            # Update global API health status
            await self.update_api_health(results)

            for key, vi in results.items():
                if not vi:
                    continue

                state = get_version_data(key)
                old_update_hash = state.get("last_update", "")

                # 1. Official Update Check
                if old_update_hash and old_update_hash != vi.version_hash:
                    logger.info(f"BloxPulse: Official Update detected for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash, is_official=True)
                    await self.broadcast_update(key, vi, old_update_hash, is_build=False)
                elif not old_update_hash:
                    logger.info(f"BloxPulse: Initializing update data for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash, is_official=True)

                # 2. Build Detection
                if key in ["WindowsPlayer", "MacPlayer"]:
                    history_entries = fetch_deploy_history(key, days=1)
                    if history_entries:
                        latest_build = history_entries[0]
                        latest_build_hash = latest_build["version_hash"]
                        old_build_hash = state.get("last_build", "")
                        
                        if latest_build_hash != old_build_hash and latest_build_hash != vi.version_hash:
                            logger.info(f"BloxPulse: Pre-release Build detected for {key} -> {latest_build_hash}")
                            update_version(key, latest_build_hash, is_official=False)
                            
                            build_vi = VersionInfo(
                                platform_key=key,
                                version=latest_build["version"],
                                version_hash=latest_build_hash,
                                channel="Build-Testing",
                                source="DeployHistory.txt"
                            )
                            await self.broadcast_update(key, build_vi, old_build_hash or old_update_hash, is_build=True)
        except Exception as e:
            logger.error(f"Error in monitor_task: {e}", exc_info=True)

    @monitor_task.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()

    async def broadcast_update(self, platform_key: str, vi: VersionInfo, prev_hash: str, is_build: bool = False):
        """Sends update/build alert to all configured guild channels."""
        guilds_data = get_all_guilds()
        for gid_str, config in guilds_data.items():
            channel_id = config.get("channel_id")
            if not channel_id: continue
            
            channel = self.bot.get_channel(channel_id)
            if not channel: continue

            lang = config.get("language", "en")
            role_id = config.get("ping_role_id")
            mention = f"<@&{role_id}>" if role_id else None
            
            state = get_version_data(platform_key)
            history_hashes = state.get("history", [])[:4]
            history_timestamps = state.get("timestamps", {})
            history_data = [{"hash": h, "date": history_timestamps.get(h, "Unknown")} for h in history_hashes]

            avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
            embed = build_update_embed(platform_key, vi, prev_hash, lang, bot_icon=avatar_url, is_build=is_build, history_data=history_data)
            view = create_language_view(platform_key, vi, prev_hash, lang)

            try:
                await channel.send(content=mention, embed=embed, view=view)
            except Exception as e:
                logger.warning(f"Could not send to guild {gid_str}: {e}")

    async def update_api_health(self, results: dict):
        """Updates global API_STATUS and triggers guild channel updates."""
        global API_STATUS
        changed = False
        for plat_key in API_STATUS.keys():
            is_on = results.get(plat_key) is not None
            if API_STATUS.get(plat_key) != is_on:
                API_STATUS[plat_key] = is_on
                changed = True
        
        if changed:
            for guild in self.bot.guilds:
                await self.update_dynamic_status(guild)

    async def update_dynamic_status(self, guild: discord.Guild):
        """Updates the status voice channels with real-time data."""
        if not guild or not hasattr(guild, "voice_channels"): return
        
        # 1. Update Member Count
        member_channel = discord.utils.get(guild.voice_channels, name=lambda n: "Members:" in n)
        if member_channel:
            try: await member_channel.edit(name=f"⬢ Members: {guild.member_count}")
            except: pass

        # 2. Update Bot Version
        version_channel = discord.utils.get(guild.voice_channels, name=lambda n: "Bot Version:" in n)
        if version_channel:
            try: await version_channel.edit(name=f"⬢ Bot Version: {BOT_VERSION}")
            except: pass

        # 3. Update API Status Channels
        status_map = {
            "Windows": API_STATUS.get("WindowsPlayer"),
            "Mac": API_STATUS.get("MacPlayer"),
            "Android": API_STATUS.get("AndroidApp"),
            "iOS": API_STATUS.get("iOS")
        }
        
        for platform, is_online in status_map.items():
            status_text = "Online" if is_online else "Offline"
            new_name = f"⬢ {platform}: {status_text}"
            chan = discord.utils.get(guild.voice_channels, name=lambda n: f"⬢ {platform}:" in n or f"❱ {platform}:" in n)
            if chan:
                try:
                    if chan.name != new_name:
                        await chan.edit(name=new_name)
                except: pass

async def setup(bot):
    # Bind update_dynamic_status to bot so other cogs can call it
    cog = MonitoringSystem(bot)
    bot.update_dynamic_status = cog.update_dynamic_status
    await bot.add_cog(cog)
