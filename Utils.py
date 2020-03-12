# Utility functions for bouncer

import discord, time, sqlite3

DATABASE_PATH = "private/sdv.db"

# This is basically a makeshift enum
class LogTypes:
    UNBAN = -3
    KICK = -2
    NOTE = -1
    BAN = 0
    WARN = 1

# Removes the first word of a string
def strip(m):
    tmp = m.split()[1:]
    return " ".join(tmp)

# Removes the '$command' to get just the request
def removeCommand(m):
    tmp = m.split()[2:]
    return " ".join(tmp)

def formatTime(t):
    # Input t is of the form: YYYY-MM-DD HH:MM:SS.SSSSSS
    date = str(t).split()[0]
    # output is of the form YYYY-MM-DD
    return date

# Checks if given user has one of the roles specified in config.json
def checkRoles(user, validRoles):
    try:
        if len(validRoles) == 1 and validRoles[0] == "":
            return True
        for role in user.roles:
            for r in validRoles:
                if role.id == r:
                    return True
        return False
    except AttributeError as e:
        print("The user {}#{} had this issue {}".format(user.name, user.discriminator, e))

# Parses the message to check if there's a valid username, then attempts to find their ID
def parseUsername(message, recentBans):
    # Usernames can have spaces, so need to throw away the first word (the command),
    # and then everything after the discriminator

    # Remove command
    testUsername = message.content.split()[1:]
    testUsername = " ".join(testUsername)
    # Remove a "@" if it exists at the front of the message
    if testUsername[0] == "@":
        testUsername = testUsername[1:]

    try:
        # Parse out the actual username
        user = testUsername.split("#")
        discriminator = user[1].split()
        user = "{}#{}".format(user[0], discriminator[0])

        userFound = discord.utils.get(message.guild.members, name=user.split("#")[0], discriminator=user.split("#")[1])
        if userFound != None:
            return str(userFound.id)

        if user in list(recentBans.values()):
            revBans = {v: k for k, v in recentBans.items()}
            return revBans[user]

        sqlconn = sqlite3.connect(DATABASE_PATH)
        searchResults = sqlconn.execute("SELECT id FROM badeggs WHERE username=?", [user]).fetchall()
        sqlconn.close()
        if searchResults != []:
            return searchResults[0][0]
        else:
            return None
    except IndexError:
        return None

# Since usernames can have spaces, first check if it's a username, otherwise just cut off first word as normal
# 'user' will either be the correct username, or an ID.
def parseMessage(message, username):
    m = " ".join(message.split()[1:])
    if m.startswith(username):
        return m[len(username)+1:]
    return removeCommand(message)

def formatMessage(info):
    logType = info[3]
    logWord = ""
    if logType == LogTypes.BAN:
        logWord = "Banned"
    elif logType == LogTypes.NOTE:
        logWord = "Note"
    elif logType == LogTypes.KICK:
        logWord = "Kicked"
    elif logType == LogTypes.UNBAN:
        logWord = "Unbanned"
    else: # LogTypes.WARN
        logWord = "Warning #{}".format(logType)

    output = "[{date}] **{name}** - {word} by {staff} - {message}\n".format(
        date = formatTime(info[4]),
        name = info[2],
        word = logWord,
        staff = info[6],
        message = info[5]
    )

    return output

def getTimeDelta(t1, t2):
    # t1 should be larger than t2
    delta = t1 - t2
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return delta.days, hours, minutes

# Combines message content and attachment URLs together
def combineMessage(mes):
    out = mes.content
    if mes.attachments != []:
        for item in mes.attachments:
            out += '\n' + item.url

    return out

#########################################################
# Functions that only need to be called once in a while #
#########################################################

# Exports the user list to a .txt file
async def fetchUserList(message):
    with open("private/users.txt", 'w') as f:
        mems = message.guild.members
        for u in mems:
            f.write("{}\n".format(u.name))

# Fetches a dict of the role names to ID values for the given server
# serverID needs to be a string
async def fetchRoleList(server):
    roles = {role.name: role.id for role in server.roles}
    out = "```\n"
    for r in roles:
        out += "{} : {}\n".format(r, roles[r])
    out += "```"
    return out

async def dumpBans(banList):
    output = ""
    for user in list(banList.items()):
        output += "{}: {}\n".format(user, banList[user])
    return output
