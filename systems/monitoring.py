# systems/monitoring.py
"""
BloxPulse · Background Monitoring System
==========================================
A discord.ext.tasks loop that polls all configured Roblox platforms,
detects version changes (official releases and pre-release builds),
broadcasts alerts to every subscribed guild, and maintains the
real-time status channels.

Responsibilities
----------------
- Run ``fetch_all()`` every CHECK_INTERVAL seconds off the event loop.
- Compare results against persisted state; persist new state on change.
- Fan-out update embeds to every guild channel in parallel (gather).
- Keep ``API_STATUS`` in sync for the REST API to consume.
- Update voice-channel status counters on change.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks

from config import BOT_AVATAR_URL, BOT_VERSION, CHECK_INTERVAL
from core.checker import VersionInfo, fetch_all
from core.history import HistoryEntry, fetch_deploy_history
from core.notifier import build_update_embed, create_language_view
from core.storage import get_all_guilds, get_version_data, update_version

log = logging.getLogger("BloxPulse.Monitoring")

# ──────────────────────────────────────────────────────────────────────────────
#  Global API health state  (consumed by the REST API layer)
# ──────────────────────────────────────────────────────────────────────────────

API_STATUS: dict[str, bool] = {
    "WindowsPlayer": True,
    "MacPlayer":     True,
    "AndroidApp":    True,
    "iOS":           True,
}

# Platforms that support pre-release build detection via DeployHistory.txt
_BUILD_DETECTION_PLATFORMS: frozenset[str] = frozenset({"WindowsPlayer", "MacPlayer"})

# Voice channel name fragments used to identify dynamic status channels
_CHANNEL_NAME_FRAGMENTS: dict[str, str] = {
    "members":  "Members:",
    "version":  "Bot Version:",
    "windows":  "Windows:",
    "mac":      "Mac:",
    "android":  "Android:",
    "ios":      "iOS:",
}


# ──────────────────────────────────────────────────────────────────────────────
#  Monitoring Cog
# ──────────────────────────────────────────────────────────────────────────────

class MonitoringSystem(commands.Cog):
    """
    Cog that owns the background version polling loop.

    The loop runs every CHECK_INTERVAL seconds, offloads the blocking
    network calls to a thread-pool executor, and then processes results
    entirely within the async event loop.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._monitor_loop.start()

    def cog_unload(self) -> None:
        self._monitor_loop.cancel()

    # ── Main loop ─────────────────────────────────────────────────────────────

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def _monitor_loop(self) -> None:
        log.info("── Monitoring cycle started ──────────────────────────────")
        try:
            await self._run_cycle()
        except Exception:
            log.exception("Unhandled exception in monitoring cycle")
        log.debug("── Monitoring cycle complete ─────────────────────────────")

    @_monitor_loop.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()
        log.info("Monitoring loop is ready.")

    @_monitor_loop.error
    async def _on_loop_error(self, error: Exception) -> None:
        log.exception("tasks.loop raised an unhandled error: %s", error)

    # ── Cycle orchestration ───────────────────────────────────────────────────

    async def _run_cycle(self) -> None:
        """
        One full check cycle:
        1. Fetch all platform versions off the event loop.
        2. Sync API health status.
        3. Detect official updates and pre-release builds.
        4. Broadcast any changes to guilds.
        """
        loop    = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, fetch_all)

        health_changed = self._sync_api_health(results)

        # Build a list of broadcast coroutines and await them concurrently
        broadcasts: list[asyncio.coroutine] = []

        for platform_key, vi in results.items():
            if vi is None:
                log.warning("No version data returned for %s", platform_key)
                continue

            state         = get_version_data(platform_key)
            old_hash      = state.get("last_update", "")
            current_hash  = vi.version_hash

            # ── Official update ────────────────────────────────────────────────
            if not old_hash:
                log.info("Initialising version record for %s → %s", platform_key, current_hash)
                update_version(platform_key, current_hash, is_official=True)

            elif old_hash != current_hash:
                log.info(
                    "🆕 Official update detected: %s  %s → %s",
                    platform_key, old_hash[:20], current_hash[:20],
                )
                update_version(platform_key, current_hash, is_official=True)
                broadcasts.append(
                    self._broadcast(platform_key, vi, prev_hash=old_hash, is_build=False)
                )

            # ── Pre-release build detection ───────────────────────────────────
            if platform_key in _BUILD_DETECTION_PLATFORMS:
                build_coro = await self._check_build(platform_key, vi, state)
                if build_coro:
                    broadcasts.append(build_coro)

        if broadcasts:
            await asyncio.gather(*broadcasts, return_exceptions=True)

        if health_changed:
            await self._refresh_all_status_channels()

    async def _check_build(
        self,
        platform_key: str,
        vi:           VersionInfo,
        state:        dict,
    ) -> Optional[asyncio.coroutine]:
        """
        Compare the latest DeployHistory.txt entry against what we have stored.
        Returns a broadcast coroutine if a new build was found, else None.
        """
        loop = asyncio.get_running_loop()
        try:
            history: list[HistoryEntry] = await loop.run_in_executor(
                None, fetch_deploy_history, platform_key, 1
            )
        except Exception as exc:
            log.warning("Build detection fetch failed for %s: %s", platform_key, exc)
            return None

        if not history:
            return None

        latest       = history[0]
        build_hash   = latest.version_hash
        old_build    = state.get("last_build", "")

        if build_hash == old_build or build_hash == vi.version_hash:
            return None

        log.info(
            "🛠️  Pre-release build detected: %s → %s",
            platform_key, build_hash[:20],
        )
        update_version(platform_key, build_hash, is_official=False)

        build_vi = VersionInfo(
            platform_key=platform_key,
            version=latest.version,
            version_hash=build_hash,
            channel="Build-Testing",
            source="DeployHistory.txt",
        )
        prev = old_build or state.get("last_update", "")
        return self._broadcast(platform_key, build_vi, prev_hash=prev, is_build=True)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast(
        self,
        platform_key: str,
        vi:           VersionInfo,
        prev_hash:    str,
        is_build:     bool,
    ) -> None:
        """
        Send an update embed to every configured guild channel.
        All guild sends run concurrently via asyncio.gather.
        """
        guilds_data = get_all_guilds()
        if not guilds_data:
            return

        state      = get_version_data(platform_key)
        history_hs = state.get("history", [])[:4]
        ts_map     = state.get("timestamps", {})
        history_data = [{"hash": h, "date": ts_map.get(h, "Unknown")} for h in history_hs]

        avatar_url = (
            self.bot.user.display_avatar.url
            if self.bot.user
            else BOT_AVATAR_URL
        )

        send_tasks = []
        for gid_str, cfg in guilds_data.items():
            channel_id = cfg.get("channel_id")
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                log.debug("Guild %s: channel %s not found or not a TextChannel", gid_str, channel_id)
                continue

            lang    = cfg.get("language", "en")
            role_id = cfg.get("ping_role_id")
            mention = f"<@&{role_id}>" if role_id else None

            embed = build_update_embed(
                platform_key, vi, prev_hash,
                lang=lang,
                bot_icon=avatar_url,
                is_build=is_build,
                history_data=history_data,
            )
            view = create_language_view(platform_key, vi, prev_hash, lang)

            send_tasks.append(
                self._safe_send(channel, content=mention, embed=embed, view=view, gid=gid_str)
            )

        if send_tasks:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            errors  = sum(1 for r in results if isinstance(r, Exception))
            if errors:
                log.warning(
                    "broadcast: %d/%d guild sends failed for %s",
                    errors, len(send_tasks), platform_key,
                )

    @staticmethod
    async def _safe_send(
        channel: discord.TextChannel,
        gid:     str,
        **kwargs,
    ) -> None:
        """Send to a single guild channel, absorbing known Discord errors."""
        try:
            await channel.send(**kwargs)
        except discord.Forbidden:
            log.warning("No permission to send in guild %s channel %s", gid, channel.id)
        except discord.HTTPException as exc:
            log.warning("HTTP error sending to guild %s: %s", gid, exc)

    # ── API health sync ───────────────────────────────────────────────────────

    def _sync_api_health(self, results: dict[str, Optional[VersionInfo]]) -> bool:
        """
        Update global API_STATUS from the latest fetch results.
        Returns True if any status changed.
        """
        changed = False
        for platform_key in list(API_STATUS.keys()):
            online = results.get(platform_key) is not None
            if API_STATUS[platform_key] != online:
                API_STATUS[platform_key] = online
                log.info(
                    "API health change: %s is now %s",
                    platform_key,
                    "ONLINE" if online else "OFFLINE",
                )
                changed = True
        return changed

    # ── Dynamic status channels ───────────────────────────────────────────────

    async def update_dynamic_status(self, guild: discord.Guild) -> None:
        """
        Update all dynamic voice-channel counters for a single guild.
        Called by other cogs (WelcomeSystem) when membership changes.
        """
        if not guild:
            return
        await self._update_status_channels(guild)

    async def _refresh_all_status_channels(self) -> None:
        """Update dynamic channels in every guild the bot is in."""
        tasks = [self._update_status_channels(g) for g in self.bot.guilds]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _update_status_channels(self, guild: discord.Guild) -> None:
        """Apply current status data to named voice channels in one guild."""
        if not guild.me or not guild.me.guild_permissions.manage_channels:
            return

        desired: dict[str, str] = {
            "Members:":    f"⬢ Members: {guild.member_count:,}",
            "Bot Version:": f"⬢ Bot Version: {BOT_VERSION}",
            "Windows:":    f"⬢ Windows: {'Online' if API_STATUS.get('WindowsPlayer') else 'Offline'}",
            "Mac:":        f"⬢ Mac: {'Online' if API_STATUS.get('MacPlayer') else 'Offline'}",
            "Android:":    f"⬢ Android: {'Online' if API_STATUS.get('AndroidApp') else 'Offline'}",
            "iOS:":        f"⬢ iOS: {'Online' if API_STATUS.get('iOS') else 'Offline'}",
        }

        for channel in guild.voice_channels:
            for fragment, new_name in desired.items():
                if fragment.lower() in channel.name.lower() and channel.name != new_name:
                    try:
                        await channel.edit(name=new_name, reason="BloxPulse status update")
                        log.debug("Updated voice channel '%s' → '%s'", channel.name, new_name)
                    except discord.Forbidden:
                        log.warning(
                            "Cannot edit voice channel '%s' in %s (Forbidden)",
                            channel.name, guild.name,
                        )
                    except discord.HTTPException as exc:
                        log.warning("Failed to update channel '%s': %s", channel.name, exc)
                    break  # only one fragment can match per channel


# ──────────────────────────────────────────────────────────────────────────────
#  Cog setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    cog = MonitoringSystem(bot)
    # Expose update_dynamic_status on the bot so other cogs can call it
    bot.update_dynamic_status = cog.update_dynamic_status
    await bot.add_cog(cog)