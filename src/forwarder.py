import discord
from client import client
import db
from waiting import AnsweringMachineEntry, is_in_home_server
import commands
import commonbot
from collections import OrderedDict
from threading import Lock


class MessageForwarder:
    """
    Handles message forwarding between bouncer DMs and server staff.

    There are two key parts of this functionality:
     - Bouncer receives DM -> forward it to staff
     - Staff replies to forwarded message -> reply to user in DMS

    The first part is here. For the second part, the reply command handles figuring out who to message and sending the message.

    We could move reply command functionality into this class, but I left it as is.
    """
    def __init__(self, create_threads: bool, mailbox_channel: int, ban_appeal_channel: int, home_server: int, staff_roles: list[int]):
        """
        Creates a new message forwarder.

        :param create_threads: Whether to forward messages into threads or not.
                               If true, threads are created under the mailbox channel.
                               If false, messages are sent directly to either the mailbox/ban appeal channel as appropriate.
        :param mailbox_channel: The channel to forward regular DMs to.
        :param ban_appeal_channel: The channel to forward ban appeal DMs to. Used only if threads are disabled.
        :param home_server: Bouncer's home server, used to make thread names nice.
        :param staff_roles: The roles containing members to add to created threads.
        """
        # Configuration
        self._create_threads = create_threads
        self._mailbox_channel = mailbox_channel
        self._ban_appeal_channel = ban_appeal_channel
        self._home_server = home_server
        self._staff_roles = staff_roles

        # Maps user ids to reply thread ids - used when receiving a DM to know which thread to forward it to (if create_threads is true)
        self._user_id_to_thread_id = LRUCache(lambda user_id: db.get_user_reply_thread_id(user_id), maxsize=50)

        # Maps user reply thread ids to user ids - used when staff replies in a thread to know which user to send the reply to (this will work for existing threads even if create_threads is false)
        self._thread_id_to_user_id = LRUCache(lambda thread_id: db.get_user_reply_thread_user_id(thread_id), maxsize=50)

        # Both of the above use an LRU cache wrapper around accessing the DB so that every DM/reply does not trigger DB access
        # The chosen cache size should be equal to the number of concurrent/active conversations we expect users to have with bouncer

    async def on_dm(self, message: discord.Message):
        """
        On a DM, forward the message to staff.

        :param message: The message that was sent.
        """
        # Ignore blocked users
        if commands.bu.is_in_blocklist(message.author.id):
            return

        # Figure out what message to send
        # If reply threads are on, everything goes to mailbox
        # Otherwise, it depends on whether it's a ban appeal or not
        if self._create_threads or is_in_home_server(message.author):  # If the user is in the home server, treat it as a regular DM
            reply_message = f"<@{message.author.id}>"
            answering_machine = commands.reply_am
            reply_channel = client.get_channel(self._mailbox_channel)
        else:  # Otherwise, assume it's a ban appeal (users must have a mutual server to message bouncer, they should only be able to join those two)
            reply_message = f"{str(message.author)} ({message.author.id}) (banned)"  # Can't ping user, so show username details
            answering_machine = commands.ban_am
            reply_channel = client.get_channel(self._ban_appeal_channel)

        # Set latest received reply so '^' works when sending the reply command
        answering_machine.set_recent_reply(message.author)

        # Fill in the rest of the message with what the user said
        content = commonbot.utils.combine_message(message)
        reply_message += f": {content}"

        # If forwarded messages should be grouped into threads, get or create the appropriate thread for the message user
        if self._create_threads:
            reply_channel = await self._get_or_create_user_reply_thread(message.author, reply_channel)

        # Forward the message to the channel/thread
        log_mes = await commonbot.utils.send_message(reply_message, reply_channel)

        try:
            # Send the user a message so they know something actually happened
            await message.channel.send("Your message has been forwarded!")
        except discord.errors.Forbidden as err:
            if err.code == 50007:
                await reply_channel.send("Unable to send message forward notification to the above user - Can't send messages to that user")
            else:
                await reply_channel.send(f"ERROR: While attempting to send message forward notification, there was an unexpected error. Tell aquova this: {err}")

        # Record that the user is waiting for a reply
        mes_entry = AnsweringMachineEntry(f"{str(message.author)}", message.created_at, content, log_mes.jump_url)
        answering_machine.update_entry(message.author.id, mes_entry)

    def get_userid_for_user_reply_thread(self, message: discord.Message) -> int | None:
        """
        Get the user id to reply to if message was sent in a reply thread.

        :param message: The staff reply message.
        :return: The user id, if message was sent in a user reply thread. None otherwise.
        """
        return self._thread_id_to_user_id(message.channel.id)

    async def _get_or_create_user_reply_thread(self, user: discord.User, parent_channel: discord.TextChannel) -> discord.Thread:
        """
        Either retrieves the existing reply thread for a user, or creates a new one if they don't have one.

        :param user: The user to get or create the reply thread for.
        :param parent_channel: The parent channel to create the reply thread in, if a new one is needed.
        :return: The existing/new thread.
        """
        thread_id = self._user_id_to_thread_id(user.id)

        if thread_id is None:
            # This is a first time user messaging bouncer -> create a reply thread for them
            return await self._create_reply_thread(user, parent_channel)

        # Get thread from thread cache (holds active threads only)
        user_reply_thread = client.get_channel(thread_id)
        if user_reply_thread is not None:
            # Active thread -> update it and use it for the conversation
            await self._update_reply_thread(user, user_reply_thread)
            return user_reply_thread

        # The thread is either archived or deleted; use fetch channel to find out which
        # The order is important: fetch channel is an API call, so we want to avoid it if possible
        try:
            user_reply_thread = await client.fetch_channel(thread_id)

            # It was archived -> send a message to notify mods someone is starting a new conversation
            await parent_channel.send(f"User <@{user.id}> sent bouncer a new message (their reply thread has been un-archived), thread link: <#{thread_id}>.")
            await self._update_reply_thread(user, user_reply_thread)
            return user_reply_thread
        except discord.errors.NotFound:
            # It was deleted
            await parent_channel.send(f"Reply thread for user <@{user.id}> was not found (it was probably deleted), creating a new one.")
            return await self._create_reply_thread(user, parent_channel)

    async def _create_reply_thread(self, user: discord.User, parent_channel: discord.TextChannel) -> discord.Thread:
        """
        Creates a reply thread for a user.

        :param user: The user to crate the reply thread for.
        :param parent_channel: The channel to create the thread in.
        :return: The new thread.
        """
        thread = await parent_channel.create_thread(name=self._user_reply_thread_name(user), type=discord.ChannelType.public_thread)

        # Update DB and caches
        db.set_user_reply_thread(user.id, thread.id)
        self._user_id_to_thread_id.set(thread.id, user.id)
        self._thread_id_to_user_id.set(user.id, thread.id)

        # Add staff to the thread
        await self._add_staff_to_thread(thread)

        return thread

    async def _add_staff_to_thread(self, thread: discord.Thread):
        """
        Adds all staff members to a thread.

        :param thread: The thread to add staff to.
        """
        content = "This is a mention to add staff to this thread: "

        message = await thread.send(content)

        content += ', '.join([f"<@&{role_id}>" for role_id in self._staff_roles])

        # By editing in a mention, we add staff to the thread without pinging them
        await message.edit(content=content)

    async def _update_reply_thread(self, user: discord.User, thread: discord.Thread):
        """
        Update a reply thread for a user. That means:
          - change the thread name to match the user's current name
          - un-archive it

        :param user: The user the thread is for.
        :param thread: The thread.
        """
        thread_name = self._user_reply_thread_name(user)

        if thread.name != thread_name or thread.archived:
            await thread.edit(name=thread_name, archived=False)

    def _user_reply_thread_name(self, user: discord.User) -> str:
        """
        Returns the name of a user reply thread for a user.

        :param user: The user to create the thread name for.
        :return: The thread name.
        """
        # Try to get their SDV nickname (will be None if they're not in the SDV server, or not in the member cache) for a nicer thread name
        member = client.get_guild(self._home_server).get_member(user.id)
        if member is not None:
            return f"{member.display_name} ({str(user)}) ({user.id})"

        # If that didn't work, use their non-SDV name
        return f"{str(user)} ({user.id})"


class LRUCache:
    """
    A custom LRU cache (https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU)).
    Differs from stdlib's functools.lru_cache in that it allows bypassing func to set values directly.

    Based on this comment: https://bugs.python.org/issue28178#msg276812.
    """
    def __init__(self, func, maxsize=128):
        """
        Creates a new instance.

        :param func: The function to call to get the value for a key if not present in the cache.
        :param maxsize: The maximum number of items to hold before evicting entries.
        """
        self._cache = OrderedDict()
        self._lock = Lock()
        self._func = func
        self._maxsize = maxsize

    def __call__(self, *args):
        """
        Retrieve the value for the given key (args).

        :param args: The key.
        :return:
        """
        with self._lock:
            # If in cache: set entry as recently used, and return it
            if args in self._cache:
                self._cache.move_to_end(args)
                return self._cache[args]

            # Not in cache: call function to get result, store in cache (this also sets the entry as recently used)
            result = self._func(*args)
            self._cache[args] = result

            # Evict the oldest entry if reached max cache size
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

            return result

    def set(self, result, *args):
        """
        Set the result for given args, bypassing func.

        :param result: The result value.
        :param args: The args that would be provided to func.
        """
        with self._lock:
            self._cache[args] = result
            self._cache.move_to_end(args)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def debug_print(self):
        print(self._cache)
