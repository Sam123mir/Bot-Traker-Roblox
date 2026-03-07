import os
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from config import DISCORD_BOT_TOKEN, BOT_VERSION, BOT_AVATAR_URL
from core.storage import get_guild_config
from core.notifier import premium_response
from systems.api_service import start_api

# ── Logging ──────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_LOG_DIR, "monitor.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BloxPulse.Main")

# ── Bot Instance ─────────────────────────────────────────────
class BloxPulseBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        # Internal flags / locks
        self.start_time = datetime.now(timezone.utc).timestamp()
        self.welcome_lock = asyncio.Lock()
        self.welcomed_guilds = set()

    async def setup_hook(self):
        """Dynamically load all extensions (Cogs) from commands/ and systems/."""
        logger.info("⬢ Loading Extensions...")
        
        # Load Systems
        for filename in os.listdir("./systems"):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await self.load_extension(f"systems.{filename[:-3]}")
                    logger.info(f"  ↳ Loaded system: {filename}")
                except Exception as e:
                    logger.error(f"  ❌ Failed to load system {filename}: {e}")

        # Load Commands
        for filename in os.listdir("./commands"):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await self.load_extension(f"commands.{filename[:-3]}")
                    logger.info(f"  ↳ Loaded command: {filename}")
                except Exception as e:
                    logger.error(f"  ❌ Failed to load command {filename}: {e}")

        logger.info("⬢ Syncing global command tree...")
        await self.tree.sync()

    async def on_ready(self):
        logger.info(f"⬢ BloxPulse Online | Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"⬢ Version: {BOT_VERSION} | Active in {len(self.guilds)} servers")
        
        activity = discord.Activity(
            type=discord.ActivityType.watching, 
            name=f"Roblox Deployments | {BOT_VERSION}"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_error(self, event, *args, **kwargs):
        logger.error(f"Unexpected event error in {event}:", exc_info=True)

# ── Initialize ───────────────────────────────────────────────
bot = BloxPulseBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for slash commands."""
    avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        await premium_response(interaction, "Access Denied", str(error), color=0xE74C3C, bot_icon=avatar_url)
    else:
        logger.error(f"Unhandled slash command error: {error}", exc_info=True)
        await premium_response(interaction, "Unexpected Error", f"`{type(error).__name__}: {error}`", color=0xE74C3C, bot_icon=avatar_url)

if __name__ == "__main__":
    # Start REST API in the background
    logger.info("Starting REST API v1...")
    start_api()
    
    # Run Discord Bot
    logger.info("Starting BloxPulse Bot...")
    bot.run(DISCORD_BOT_TOKEN)
