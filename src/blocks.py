import discord

import db

class BlockedUsers:
    def __init__(self):
        block_db = db.get_blocklist()
        self.blocklist = [x[0] for x in block_db]

    def handle_block(self, user: discord.Member, block: bool) -> str:
        is_blocked = self._is_in_blocklist(user.id)
        if block:
            if is_blocked:
                return "Um... That user was already blocked..."
            else:
                self._block_user(user.id)
                return f"I have now blocked {str(user)}. Their DMs will no longer be forwarded."
        else:
            if not is_blocked:
                return "That user hasn't been blocked..."
            else:
                self._unblock_user(user.id)
                return f"I have now unblocked {str(user)}. Their DMs will now be forwarded."

    def _block_user(self, userid: int):
        db.add_block(userid)
        self.blocklist.append(userid)

    def _unblock_user(self, userid: int):
        db.remove_block(userid)
        self.blocklist.remove(userid)

    def _is_in_blocklist(self, userid: int) -> bool:
        return userid in self.blocklist
