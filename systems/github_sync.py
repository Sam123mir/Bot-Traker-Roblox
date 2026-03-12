import asyncio
import logging
import os
import subprocess
from discord.ext import commands, tasks

log = logging.getLogger("BloxPulse.GitHubSync")

class GitHubSync(commands.Cog):
    """
    Background loops that commits and pushes the data/ directory 
    to the GitHub repository to avoid data loss on ephemeral file systems.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.github_repo = os.environ.get("GITHUB_REPO")  # Format: Username/Repo
        self.branch = os.environ.get("GITHUB_BRANCH", "main")
        
        if self.github_token and self.github_repo:
            log.info("GitHub Sync enabled for %s", self.github_repo)
            # Setup Git config for the first time
            self._run_cmd(["git", "config", "--global", "user.name", "BloxPulse Bot"])
            self._run_cmd(["git", "config", "--global", "user.email", "bot@bloxpulsedev.local"])
            # Update remote with token
            remote_url = f"https://oauth2:{self.github_token}@github.com/{self.github_repo}.git"
            self._run_cmd(["git", "remote", "set-url", "origin", remote_url])
            
            self._sync_loop.start()
        else:
            log.warning("GitHub Sync disabled. GITHUB_TOKEN or GITHUB_REPO missing.")

    def cog_unload(self):
        if self._sync_loop.is_running():
            self._sync_loop.cancel()
    
    def _run_cmd(self, cmd: list[str]) -> str:
        """Helper to run a process synchronously and return its output"""
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            # We don't log the full command to avoid leaking tokens if they fail
            log.debug("Git command failed (Code %s): %s", e.returncode, e.stderr.strip())
            return ""

    async def _perform_sync(self):
        """Runs the actual git commands in a separate thread"""
        loop = asyncio.get_running_loop()
        
        # 1. Add changes in data directory
        await loop.run_in_executor(None, self._run_cmd, ["git", "add", "data/"])
        
        # 2. Check if we actually have things to commit (status --porcelain)
        status = await loop.run_in_executor(None, self._run_cmd, ["git", "status", "--porcelain", "data/"])
        if not status:
            log.debug("No new data to sync to GitHub.")
            return

        # 3. Commit with [skip ci] so Render doesn't loop deployments
        commit_msg = "Auto-sync bot data [skip ci] [skip render]"
        await loop.run_in_executor(None, self._run_cmd, ["git", "commit", "-m", commit_msg])
        
        # 4. Push to main branch
        await loop.run_in_executor(None, self._run_cmd, ["git", "push", "origin", self.branch])
        log.info("Successfully pushed updated data/ to GitHub.")

    @tasks.loop(minutes=5)
    async def _sync_loop(self):
        try:
            log.debug("Starting GitHub data sync cycle...")
            await self._perform_sync()
        except Exception as e:
            log.error("Unhandled error during GitHub sync: %s", getattr(e, "message", str(e)))

    @_sync_loop.before_loop
    async def _before_sync(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(GitHubSync(bot))
