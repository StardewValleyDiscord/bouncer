from datetime import timedelta, datetime

import discord

from utils import send_message

POST_MAX_QUEUE = 5                      # Max number of posts to queue before sending
POST_MAX_DELTA = timedelta(minutes=5)   # Max amount of time posts should remain in queue

class Syslog:
    def __init__(self):
        self.logs = []
        self.oldest = None

    def setup(self, syslog: discord.TextChannel):
        self.channel = syslog

    async def add_log(self, message: str):
        self.logs.append(message)
        now = datetime.now()
        if self.oldest is None:
            self.oldest = now
        if len(self.logs) >= POST_MAX_QUEUE or now - self.oldest > POST_MAX_DELTA:
            # Note that this means we only have the potential to post logs when a loggable event fires
            # Given the activity on the server, this seems likely to occur within the max delta time, but other solutions might be needed
            # This also probably can have a race condition, so watch out for that
            await self._post_logs()

    async def _post_logs(self):
        joined = '\n'.join(self.logs)
        await send_message(joined, self.channel)
        self.logs.clear()
        self.oldest = None
