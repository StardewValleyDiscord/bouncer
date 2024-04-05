from typing import cast

import discord
from discord.ext import commands

from blocks import BlockedUsers
from config import LOG_CHAN, MAILBOX, SPAM_CHAN, SYS_LOG, WATCHLIST_CHAN
import db
from spam import Spammers
from syslog import Syslog
from waiting import AnsweringMachine
from watcher import Watcher

class DiscordClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        # The command prefix is never used, but we have to have something
        super().__init__(command_prefix="$", intents=intents)
        db.initialize()

        self.am = AnsweringMachine()
        self.blocks = BlockedUsers()
        self.spammers = Spammers()
        self.syslog = Syslog()
        self.watch = Watcher()

    async def set_channels(self):
        self.mailbox = cast(discord.TextChannel, self.get_channel(MAILBOX))
        self.log = cast(discord.TextChannel, self.get_channel(LOG_CHAN))
        self.spam = cast(discord.TextChannel, self.get_channel(SPAM_CHAN))
        self.watchlist = cast(discord.TextChannel, self.get_channel(WATCHLIST_CHAN))

        if not self.syslog.is_loaded():
            self.syslog.setup(self.get_channel(SYS_LOG))
            await self.add_cog(self.syslog)

    async def sync_guild(self, guild: discord.Guild):
        import context
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = DiscordClient()
