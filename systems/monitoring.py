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
- Fan-out update embeds to every guild channel in parallel (asyncio.gather).
- Keep ``API_STATUS`` and ``API_LATENCY`` in sync for the REST API.
- Update voice-channel status counters on change.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks

from config import BOT_AVATAR_URL, BOT_VERSION, CHECK_INTERVAL
from core.checker import VersionInfo, fetch_all, fetch_version
from core.history import HistoryEntry, fetch_deploy_history
from core.notifier import build_update_embed, create_language_view
from core.storage import get_all_guilds, get_version_data, update_version

log = logging.getLogger("BloxPulse.Monitoring")


# ──────────────────────────────────────────────────────────────────────────────
#  Global API Health State  (consumed by the REST API layer)
# ──────────────────────────────────────────────────────────────────────────────

API_STATUS: dict[str, bool] = {
    "WindowsPlayer": True,
    "MacPlayer":     True,
    "AndroidApp":    True,
    "iOS":           True,
}

API_LATENCY: dict[str, Optional[int]] = {
    "WindowsPlayer": None,
    "MacPlayer":     None,
    "AndroidApp":    None,
    "iOS":           None,
}

# Platforms that support pre-release build detection via DeployHistory.txt
_BUILD_DETECTION_PLATFORMS: frozenset[str] = frozenset({"WindowsPlayer", "MacPlayer"})

# Cooldown for Discord voice-channel renames (Discord limit: 2 per 10 min per channel)
_CHANNEL_RENAME_COOLDOWN: float = 360.0   # 6 minutes — safe margin


def _latency_emoji(latency_ms: Optional[int]) -> str:
    """Return a coloured dot emoji based on API response time."""
    if latency_ms is None:    return "🔴"   # Offline / unreachable
    if latency_ms < 600:      return "🟢"   # Fast
    if latency_ms < 1_500:    return "🟡"   # Normal
    if latency_ms < 3_000:    return "🟠"   # Slow
    return "🔴"                              # Very slow / degraded


# ──────────────────────────────────────────────────────────────────────────────
#  Monitoring Cog
# ──────────────────────────────────────────────────────────────────────────────

class MonitoringSystem(commands.Cog):
    """
    Cog that owns the background version polling loop.

    The loop offloads all blocking network calls to a thread-pool executor,
    then processes results entirely within the async event loop.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_channel_edit: dict[int, float] = {}
        self._monitor_loop.start()

    def cog_unload(self) -> None:
        self._monitor_loop.cancel()
        log.info("Monitoring loop cancelled (cog unloaded).")

    # ── Main loop ─────────────────────────────────────────────────────────────

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def _monitor_loop(self) -> None:
        log.debug("── Monitoring cycle started ──")
        try:
            await self._run_cycle()
        except Exception:
            log.exception("Unhandled exception in monitoring cycle.")
        log.debug("── Monitoring cycle complete ──")

    @_monitor_loop.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()
        log.info("Monitoring loop ready — polling every %ds.", CHECK_INTERVAL)

    @_monitor_loop.error
    async def _on_loop_error(self, error: Exception) -> None:
        log.exception("tasks.loop raised an unhandled error: %s", error)

    # ── Cycle orchestration ───────────────────────────────────────────────────

    async def _run_cycle(self) -> None:
        """
        One full check cycle:
          1. Fetch all platform versions off the event loop.
          2. Compare against persisted state; queue any broadcasts.
          3. Fire all broadcasts concurrently.
          4. Sync API health; refresh dynamic channels if health changed.
        """
        from config import MONITORED_CHANNELS, PC_STUDIO_PLATFORMS, PLATFORMS

        loop             = asyncio.get_running_loop()
        broadcasts:  list = []
        live_results:    dict[str, Optional[VersionInfo]] = {}
        live_latency:    dict[str, int]                   = {}

        # ── Poll every platform / channel combination ──────────────────────
        for platform_key in PLATFORMS:
            channels = MONITORED_CHANNELS if platform_key in PC_STUDIO_PLATFORMS else ["LIVE"]

            for channel in channels:
                t0 = time.perf_counter()
                vi = await loop.run_in_executor(None, fetch_version, platform_key, channel)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                # Only track LIVE data for global health stats
                if channel == "LIVE":
                    live_results[platform_key] = vi
                    if vi is not None:
                        live_latency[platform_key] = elapsed_ms

                if vi is None:
                    continue

                state        = get_version_data(platform_key, channel=channel)
                old_hash     = state.get("last_update", "")
                old_fflags   = state.get("fflag_count", 0)
                curr_hash    = vi.version_hash
                curr_fflags  = vi.fflag_count

                is_ver_change   = bool(old_hash) and old_hash != curr_hash
                is_flag_change  = old_fflags != 0 and old_fflags != curr_fflags

                if not old_hash:
                    # First-time initialisation — save state, skip broadcast
                    log.info("Init [%s:%s] → %s", platform_key, channel, curr_hash)
                    await self._persist_state(platform_key, channel, vi)

                elif is_ver_change or is_flag_change:
                    if is_ver_change:
                        log.info(
                            "🆕 Version change [%s:%s] %s → %s",
                            platform_key, channel, old_hash[:10], curr_hash[:10],
                        )
                    if is_flag_change:
                        log.info(
                            "🛠️ FFlag change [%s:%s] %d → %d",
                            platform_key, channel, old_fflags, curr_fflags,
                        )

                    await self._persist_state(platform_key, channel, vi)
                    broadcasts.append(
                        self._broadcast(
                            platform_key=platform_key,
                            vi=vi,
                            prev_hash=old_hash,
                            is_build=(channel != "LIVE"),
                            channel=channel,
                        )
                    )

            # ── Extra: Active build detection (DeployHistory.txt) ─────────────
            if platform_key in _BUILD_DETECTION_PLATFORMS:
                try:
                    entries = await loop.run_in_executor(
                        None, fetch_deploy_history, platform_key, 1 # Only last 24h
                    )
                    if entries:
                        latest_build = entries[0]
                        state = get_version_data(platform_key, channel="LIVE")
                        
                        # We only care if this hash is NOT in our history yet
                        if latest_build.version_hash not in state.get("history", []):
                            log.info("🚀 New build detected on CDN: %s (%s)", platform_key, latest_build.version_hash)
                            
                            # Convert HistoryEntry to VersionInfo for broadcasting
                            vi_build = VersionInfo(
                                platform_key=platform_key,
                                version=latest_build.version,
                                version_hash=latest_build.version_hash,
                                channel="CDN-Build",
                                source="DeployHistory.txt",
                                fflag_count=0 
                            )
                            
                            # Persist as a non-official build so we don't update 'current'
                            update_version(platform_key, vi_build.version_hash, is_official=False)
                            
                            broadcasts.append(
                                self._broadcast(
                                    platform_key=platform_key,
                                    vi=vi_build,
                                    prev_hash=state.get("current", ""),
                                    is_build=True,
                                    channel="BUILD",
                                )
                            )
                except Exception as exc:
                    log.warning("Active build detection failed for %s: %s", platform_key, exc)

        # ── Fire all broadcasts in parallel ───────────────────────────────
        if broadcasts:
            results = await asyncio.gather(*broadcasts, return_exceptions=True)
            errors  = sum(1 for r in results if isinstance(r, Exception))
            if errors:
                log.warning("%d broadcast task(s) raised exceptions this cycle.", errors)

        # ── Sync health state; refresh channels if emoji tier changed ──────
        if self._sync_api_health(live_results, live_latency):
            await self._refresh_all_status_channels()

    # ── State persistence ─────────────────────────────────────────────────────

    async def _persist_state(
        self,
        platform_key: str,
        channel: str,
        vi: VersionInfo,
    ) -> None:
        """
        Save the newly detected version to storage.
        On first-time LIVE init, also attempts to backfill deploy history.
        """
        from core.storage import backfill_history

        state = get_version_data(platform_key, channel=channel)

        # Backfill history for desktop platforms on first-ever run
        if not state.get("history") and channel == "LIVE":
            try:
                loop    = asyncio.get_running_loop()
                entries = await loop.run_in_executor(
                    None, fetch_deploy_history, platform_key, 30
                )
                if entries:
                    backfill_history(platform_key, [e.as_dict() for e in entries])
                    log.info("Backfilled %d history entries for %s.", len(entries), platform_key)
            except Exception as exc:
                log.warning("History backfill failed for %s: %s", platform_key, exc)

        update_version(
            platform_key,
            vi.version_hash,
            is_official=True,
            channel=channel,
            fflag_count=vi.fflag_count,
        )

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def _broadcast(
        self,
        platform_key: str,
        vi:           VersionInfo,
        prev_hash:    str,
        is_build:     bool,
        channel:      str = "LIVE",
    ) -> None:
        """
        Fan-out an update embed to every configured guild channel.
        Each guild send runs concurrently via asyncio.gather.
        """
        guilds_data = get_all_guilds()
        if not guilds_data:
            return

        state        = get_version_data(platform_key)
        history_hs   = state.get("history", [])[:4]
        ts_map       = state.get("timestamps", {})
        history_data = [{"hash": h, "date": ts_map.get(h, "Unknown")} for h in history_hs]

        avatar_url = (
            self.bot.user.display_avatar.url
            if self.bot.user
            else BOT_AVATAR_URL
        )

        send_tasks = []
        for gid_str, cfg in guilds_data.items():
            channel_id      = cfg.get("channel_id")
            if not channel_id:
                continue
            discord_channel = self.bot.get_channel(int(channel_id))
            if not isinstance(discord_channel, discord.TextChannel):
                log.debug(
                    "Guild %s: channel %s not found or not a TextChannel.",
                    gid_str, channel_id,
                )
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
                channel=channel,
            )
            view = create_language_view(platform_key, vi, prev_hash, lang)

            send_tasks.append(
                self._safe_send(discord_channel, gid=gid_str, content=mention, embed=embed, view=view)
            )

        if send_tasks:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            errors  = sum(1 for r in results if isinstance(r, Exception))
            if errors:
                log.warning(
                    "broadcast [%s]: %d/%d send(s) failed.",
                    platform_key, errors, len(send_tasks),
                )

    @staticmethod
    async def _safe_send(
        channel: discord.TextChannel,
        gid: str,
        **kwargs,
    ) -> None:
        """Send to one guild channel, absorbing known Discord errors gracefully."""
        try:
            await channel.send(**kwargs)
        except discord.Forbidden:
            log.warning("No send permission: guild %s, channel %s.", gid, channel.id)
        except discord.HTTPException as exc:
            log.warning("HTTP error sending to guild %s: %s", gid, exc)

    # ── API health tracking ───────────────────────────────────────────────────

    def _sync_api_health(
        self,
        results: dict[str, Optional[VersionInfo]],
        latency: dict[str, int],
    ) -> bool:
        """
        Update ``API_STATUS`` and ``API_LATENCY`` from fresh polling data.

        Returns ``True`` only when the *emoji tier* of any platform changes,
        preventing unnecessary Discord channel renames on minor latency shifts.
        """
        changed = False

        for platform_key in list(API_STATUS):
            online          = results.get(platform_key) is not None
            current_latency = latency.get(platform_key) if online else None

            old_emoji = _latency_emoji(
                API_LATENCY.get(platform_key) if API_STATUS.get(platform_key) else None
            )
            new_emoji = _latency_emoji(current_latency if online else None)

            API_STATUS[platform_key]  = online
            API_LATENCY[platform_key] = current_latency

            if old_emoji != new_emoji:
                log.info(
                    "API health [%s]: %s → %s  (%s ms)",
                    platform_key, old_emoji, new_emoji,
                    current_latency if current_latency is not None else "N/A",
                )
                changed = True

        return changed

    # ── Dynamic status channels ───────────────────────────────────────────────

    async def update_dynamic_status(self, guild: discord.Guild) -> None:
        """
        Update dynamic voice-channel counters for a single guild.
        Called externally by WelcomeSystem on member join / leave.
        """
        if guild:
            await self._update_status_channels(guild)

    async def _refresh_all_status_channels(self) -> None:
        """Push current status data to every guild's dynamic channels."""
        await asyncio.gather(
            *(self._update_status_channels(g) for g in self.bot.guilds),
            return_exceptions=True,
        )

    async def _update_status_channels(self, guild: discord.Guild) -> None:
        """Apply current status data to named voice channels in one guild."""
        if not guild.me or not guild.me.guild_permissions.manage_channels:
            return

        desired: dict[str, str] = {
            "members:":     f"》 Members: {guild.member_count}",
            "bot version:": f"》 Bot Version: {BOT_VERSION}",
        }

        for vc in guild.voice_channels:
            name_lower = vc.name.lower()
            for fragment, new_name in desired.items():
                if fragment not in name_lower:
                    continue
                if vc.name == new_name:
                    break  # Already up-to-date

                now = time.time()

                # Resolve cooldown source: welcome system shares member count cooldown
                if fragment == "members:":
                    from systems.welcome import _last_member_count_edit as _wlc
                    last_edit = _wlc.get(vc.id, 0.0)
                else:
                    last_edit = self._last_channel_edit.get(vc.id, 0.0)

                remaining = _CHANNEL_RENAME_COOLDOWN - (now - last_edit)
                if remaining > 0:
                    log.debug(
                        "Skipping rename for '%s' — cooldown %.0fs remaining.",
                        vc.name, remaining,
                    )
                    break

                try:
                    await vc.edit(name=new_name, reason="BloxPulse — status update")
                    if fragment == "members:":
                        from systems.welcome import _last_member_count_edit as _wlc
                        _wlc[vc.id] = now
                    else:
                        self._last_channel_edit[vc.id] = now
                    log.debug("Renamed '%s' → '%s'.", vc.name, new_name)

                except discord.Forbidden:
                    log.warning(
                        "Cannot rename voice channel '%s' in %s (Forbidden).",
                        vc.name, guild.name,
                    )
                except discord.HTTPException as exc:
                    if exc.status == 429:
                        # Rate-limited: apply a 10-minute penalty cooldown
                        penalty = now + 600.0
                        log.warning(
                            "Rate limited renaming '%s'. Applying 10 min penalty.",
                            vc.name,
                        )
                        if fragment == "members:":
                            from systems.welcome import _last_member_count_edit as _wlc
                            _wlc[vc.id] = penalty
                        else:
                            self._last_channel_edit[vc.id] = penalty
                    else:
                        log.warning("HTTP error renaming '%s': %s", vc.name, exc)
                break  # Each channel can only match one fragment


# ──────────────────────────────────────────────────────────────────────────────
#  Cog Setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    cog = MonitoringSystem(bot)
    # Expose helper on the bot instance for cross-cog calls (e.g. WelcomeSystem)
    bot.update_dynamic_status = cog.update_dynamic_status
    await bot.add_cog(cog)