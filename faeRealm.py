"""
🪶 The Angelic Bot 🪶
An angel-themed Discord games + counting bot.
A realm where the holy and the fallen coexist — wings of light, shadows of grace.

Games:
  !sanctum     - Show all commands
  !edict       - Today's daily challenge & streak
  !prophecy    - Trivia (Prophecies of the Eternal Scroll)
  !trial       - Rock Paper Scissors (Trial of Dominion)
  !cast        - Dice roll (Cast of Fate)
  !halo        - Pong (Halo Deflection Duel)
  !sigil       - Tic-Tac-Toe (Battle of Sigils)
  !divine      - Magic 8-Ball (The Divine Speaks)
  !ascendancy  - Leaderboard (The Ascendancy Rankings)

Feather Counter:
  !feathers setup              - Make this channel the counting channel
  !feathers shame <role name>  - Set the shame role for ruiners
  !feathers leaderboard        - Top counters & worst ruiners
  !feathers milestones         - List all milestone numbers
  !feathers status             - Show current count & high score
  !feathers reset              - Manually reset the count (admin)
  !feathers remove             - Stop watching this channel
"""

import discord
from discord.ext import commands, tasks
import random
import re
import aiohttp
import asyncio
import datetime
import os
import json
from collections import defaultdict

# ── Bot setup ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ── Persistent state ───────────────────────────────────────────────────────────
scores: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
streaks: dict[int, dict[int, dict]] = defaultdict(
    lambda: defaultdict(lambda: {"streak": 0, "last_date": None, "completed_today": False})
)
active_ttt: dict[int, dict] = {}
active_pong: dict[int, dict] = {}

# ── 🪶 Feather Counter state ───────────────────────────────────────────────────
count_state: dict[int, dict] = {}
count_board: dict[int, dict[int, dict]] = defaultdict(
    lambda: defaultdict(lambda: {"counts": 0, "ruins": 0})
)

feathers_log: dict[int, list[str]] = defaultdict(list)  # guild_id -> recent log lines
MAX_LOG = 20


def log_feathers(guild_id: int, msg: str):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    feathers_log[guild_id].append(f"`{timestamp}` {msg}")
    feathers_log[guild_id] = feathers_log[guild_id][-MAX_LOG:]
COUNT_MILESTONE_MSGS = {
    10:    "🪶 *A gentle wind stirs… ten feathers have fallen.*",
    25:    "✨ *The seraphim take notice — twenty-five feathers gathered.*",
    50:    "☁️ *The clouds part above… fifty feathers counted.*",
    100:   "😇 *The Celestial choir hums! One hundred feathers!*",
    250:   "🌤️ *Light breaks through the veil — two hundred and fifty!*",
    500:   "👼 *Five hundred feathers! Even the fallen bow their heads.*",
    1000:  "🌟 **ONE THOUSAND FEATHERS! Heaven and hell both take notice!**",
    2500:  "🪶✨ **Two thousand five hundred… your devotion is legendary.**",
    5000:  "😇 **FIVE THOUSAND. The seraphim weep with joy.**",
    10000: "🌟🪶🌟 **TEN THOUSAND FEATHERS. You have ascended beyond mortal comprehension.** 🌟🪶🌟",
}


def add_win(guild_id: int, user_id: int, amount: int = 1):
    scores[guild_id][user_id] += amount
    _save_scores()


# ── Angel flavor text ──────────────────────────────────────────────────────────
ANGEL_GREETINGS = [
    "A feather drifts from the heavens…",
    "Wings stir in the silence…",
    "The Celestial Court turns its gaze…",
    "Light fractures through the clouds…",
    "A halo flickers in the dark…",
]

ANGEL_WIN = [
    "Heaven smiles upon you! 😇",
    "Your wings shine brighter! ✨",
    "Even the fallen acknowledge your grace! 🪶",
    "The seraphim sing your name! 🌟",
]

ANGEL_LOSE = [
    "The shadows close in… 🌑",
    "A fallen angel grins. 😈",
    "Perhaps in another life, mortal. ☁️",
    "Your halo dims… for now. 🌫️",
]

ANGEL_TIE = [
    "Holy and fallen stand equal — a draw! ⚖️",
    "Neither light nor shadow prevails… 🌓",
    "The Celestial Court declares a stalemate! 🪶",
]

def flavor(lst): return random.choice(lst)


# ── Daily Edict (daily challenge + streaks) ────────────────────────────────────
DAILY_CHALLENGES = [
    {"task": "Win a game of **!trial** (Rock Paper Scissors)", "cmd": "trial"},
    {"task": "Answer a **!prophecy** correctly", "cmd": "prophecy"},
    {"task": "Win a game of **!sigil** (Tic-Tac-Toe)", "cmd": "sigil"},
    {"task": "Roll a **natural 20** with `!cast d20`", "cmd": "cast"},
    {"task": "Win a game of **!halo** (Pong)", "cmd": "halo"},
    {"task": "Ask **!divine** three questions", "cmd": "divine"},
    {"task": "Find all words in **!wordsearch**", "cmd": "wordsearch"},
]

def get_today_challenge():
    today = datetime.date.today()
    idx = today.toordinal() % len(DAILY_CHALLENGES)
    return DAILY_CHALLENGES[idx]


@bot.command(name="edict", help="See today's Daily Edict and your streak.")
async def edict(ctx):
    challenge = get_today_challenge()
    user_data = streaks[ctx.guild.id][ctx.author.id]
    today = str(datetime.date.today())
    completed = user_data["completed_today"] and user_data["last_date"] == today
    streak = user_data["streak"]

    embed = discord.Embed(
        title="📜 The Daily Edict",
        description=(
            f"*{flavor(ANGEL_GREETINGS)}*\n\n"
            f"Today's divine trial:\n> {challenge['task']}"
        ),
        color=0xF0C040,
    )
    embed.add_field(name="Your Streak",    value=f"🔥 **{streak}** day{'s' if streak != 1 else ''}", inline=True)
    embed.add_field(name="Today's Status", value="✅ **Completed!**" if completed else "⏳ **Pending…**", inline=True)
    embed.set_footer(text="Complete the edict to keep your streak alive! Resets at midnight.")
    await ctx.send(embed=embed)


def complete_edict(guild_id: int, user_id: int, cmd: str):
    challenge = get_today_challenge()
    if challenge["cmd"] != cmd:
        return False
    today = str(datetime.date.today())
    user_data = streaks[guild_id][user_id]
    if user_data["completed_today"] and user_data["last_date"] == today:
        return False
    yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
    if user_data["last_date"] == yesterday:
        user_data["streak"] += 1
    else:
        user_data["streak"] = 1
    user_data["last_date"] = today
    user_data["completed_today"] = True
    _save_streaks()
    return True


# ── 🎲 Cast of Fate (Dice Roll) ───────────────────────────────────────────────
@bot.command(name="cast", help="Cast the dice of fate. Usage: !cast 2d6 or !cast d20")
async def cast(ctx, dice: str = "1d6"):
    match = re.fullmatch(r"(\d+)?d(\d+)", dice.lower())
    if not match:
        await ctx.send("❌ *The heavens cannot parse that.* Try `!cast 2d6` or `!cast d20`.")
        return

    num = int(match.group(1) or 1)
    sides = int(match.group(2))

    if not (1 <= num <= 100) or not (2 <= sides <= 1000):
        await ctx.send("❌ *Even angels have limits.* Keep dice between 1–100 and sides 2–1000.")
        return

    rolls = [random.randint(1, sides) for _ in range(num)]
    total = sum(rolls)
    nat20 = sides == 20 and num == 1 and total == 20

    embed = discord.Embed(
        title="🎲 Cast of Fate",
        description=f"*{flavor(ANGEL_GREETINGS)}*",
        color=0xFFD700 if nat20 else 0xC8A96E,
    )
    embed.add_field(name="Roll",   value=f"`{dice}`", inline=True)
    embed.add_field(name="Result", value=f"**{total}**{'  🌟 NATURAL 20!' if nat20 else ''}", inline=True)
    if num > 1:
        embed.add_field(name="Breakdown", value=", ".join(str(r) for r in rolls), inline=False)
    embed.set_footer(text=f"Cast by {ctx.author.display_name}")

    if nat20:
        edict_done = complete_edict(ctx.guild.id, ctx.author.id, "cast")
        if edict_done:
            embed.add_field(
                name="📜 Edict Fulfilled!",
                value="The heavens rejoice! Your streak lives on! 🔥",
                inline=False,
            )
        add_win(ctx.guild.id, ctx.author.id)

    await ctx.send(embed=embed)


# ── ❓ Prophecies of the Eternal Scroll (Trivia) ───────────────────────────────
@bot.command(name="prophecy", help="Answer a prophecy from the Eternal Scroll.")
async def prophecy(ctx):
    url = "https://opentdb.com/api.php?amount=1&type=multiple"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ *The Scroll is sealed… try again later.*")
                return
            data = await resp.json()

    q = data["results"][0]
    correct = q["correct_answer"]
    all_answers = q["incorrect_answers"] + [correct]
    random.shuffle(all_answers)
    letters = ["A", "B", "C", "D"]
    correct_letter = letters[all_answers.index(correct)]

    choices_text = "\n".join(f"**{letters[i]}**. {ans}" for i, ans in enumerate(all_answers))
    embed = discord.Embed(
        title="📜 A Prophecy from the Eternal Scroll",
        description=f"*The heavens part and the Scroll speaks…*\n\n{q['question']}",
        color=0xF0C040,
    )
    embed.add_field(name="Choices",    value=choices_text,              inline=False)
    embed.add_field(name="Domain",     value=q["category"],             inline=True)
    embed.add_field(name="Difficulty", value=q["difficulty"].capitalize(), inline=True)
    embed.set_footer(text="Reply with A, B, C, or D within 30 seconds…")
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in letters

    try:
        msg = await bot.wait_for("message", timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send(f"⏰ *The Scroll seals itself.* The answer was **{correct_letter}. {correct}**.")
        return

    if msg.content.upper() == correct_letter:
        add_win(ctx.guild.id, ctx.author.id)
        edict_done = complete_edict(ctx.guild.id, ctx.author.id, "prophecy")
        reply = f"✅ {flavor(ANGEL_WIN)} {ctx.author.mention} read the prophecy correctly!"
        if edict_done:
            reply += "\n📜 **Daily Edict fulfilled! Streak extended! 🔥**"
        await ctx.send(reply)
    else:
        await ctx.send(f"❌ {flavor(ANGEL_LOSE)} The answer was **{correct_letter}. {correct}**.")


# ── ⚔️ Trial of Dominion (Rock Paper Scissors) ────────────────────────────────
TRIAL_CHOICES = {"light": "✨", "shadow": "🌑", "feather": "🪶"}
TRIAL_WINS    = {"light": "shadow", "shadow": "feather", "feather": "light"}
TRIAL_FLAVOR  = {
    "light":   "a beam of holy light",
    "shadow":  "a tendril of fallen shadow",
    "feather": "an angel's feather",
}

@bot.command(name="trial", help="Enter the Trial of Dominion. Usage: !trial light/shadow/feather")
async def trial(ctx, choice: str = ""):
    choice = choice.lower()
    if choice not in TRIAL_CHOICES:
        await ctx.send("❌ *Choose your weapon:* `light`, `shadow`, or `feather`. Example: `!trial light`")
        return

    bot_choice = random.choice(list(TRIAL_CHOICES))
    you_emoji  = TRIAL_CHOICES[choice]
    bot_emoji  = TRIAL_CHOICES[bot_choice]

    if choice == bot_choice:
        result, color = flavor(ANGEL_TIE), 0xFFFF00
    elif TRIAL_WINS[choice] == bot_choice:
        result, color = flavor(ANGEL_WIN), 0x57F287
        add_win(ctx.guild.id, ctx.author.id)
        edict_done = complete_edict(ctx.guild.id, ctx.author.id, "trial")
        if edict_done:
            result += "\n📜 **Daily Edict fulfilled! Streak extended! 🔥**"
    else:
        result, color = flavor(ANGEL_LOSE), 0xED4245

    embed = discord.Embed(title="⚔️ Trial of Dominion", color=color)
    embed.add_field(name="You wielded",      value=f"{you_emoji} {TRIAL_FLAVOR[choice].capitalize()}", inline=True)
    embed.add_field(name="The Court chose",  value=f"{bot_emoji} {TRIAL_FLAVOR[bot_choice].capitalize()}", inline=True)
    embed.add_field(name="Verdict",          value=result, inline=False)
    await ctx.send(embed=embed)


# ── 🔮 The Divine (Magic 8-Ball) ──────────────────────────────────────────────
DIVINE_RESPONSES = [
    "The heavens whisper *yes*. 😇",
    "An angel nods — *it shall be so*. 🪶",
    "The seraphim sing in agreement! ✨",
    "Light floods your path — *yes*. ☀️",
    "Even the fallen believe this to be true. 🌟",
    "The clouds part… and show *yes*. ☁️",
    "The Celestial Court is… *uncertain*. Ask again at dawn. 🌅",
    "A halo flickers — *the answer is unclear*. 👼",
    "Holy and fallen argue about this one. ⚖️",
    "The veil between worlds is too thick. 🌫️",
    "A fallen feather lands at your feet — *not yet*. 🪶",
    "Even the angels shake their heads. *No.* 🌑",
    "The Celestial Court forbids it. ⚔️",
    "Dark clouds gather — *do not pursue this*. ☁️",
    "Even the most merciful angel says *nay*. 😇",
]

divine_uses: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

@bot.command(name="divine", help="Seek divine guidance. Usage: !divine Will I win?")
async def divine(ctx, *, question: str = ""):
    if not question:
        await ctx.send("❓ *Speak your question to the heavens.* Example: `!divine Will I win?`")
        return

    divine_uses[ctx.guild.id][ctx.author.id] = divine_uses[ctx.guild.id].get(ctx.author.id, 0) + 1
    uses_today = divine_uses[ctx.guild.id][ctx.author.id]

    answer = random.choice(DIVINE_RESPONSES)
    embed = discord.Embed(
        title="✨ The Divine Speaks",
        description=f"*A soul dares to ask the heavens…*\n\n_{question}_",
        color=0xF0C040,
    )
    embed.add_field(name="The answer is revealed", value=answer, inline=False)

    if uses_today >= 3:
        edict_done = complete_edict(ctx.guild.id, ctx.author.id, "divine")
        if edict_done:
            embed.add_field(
                name="📜 Edict Fulfilled!",
                value="Three questions asked. Heaven is satisfied. 🔥",
                inline=False,
            )
    embed.set_footer(text=f"Questions asked today: {uses_today}")
    await ctx.send(embed=embed)


# ── 🏓 Halo Deflection Duel (Pong) ────────────────────────────────────────────
@bot.command(name="halo", help="Play the Halo Deflection Duel (Pong)! Usage: !halo")
async def halo(ctx):
    if ctx.channel.id in active_pong:
        await ctx.send("😇 *A duel is already taking place in this channel!*")
        return

    active_pong[ctx.channel.id] = True
    player_score = 0
    bot_score = 0
    rally = 0

    async def send_embed(description, color=0xF0C040):
        embed = discord.Embed(title="😇 Halo Deflection Duel", description=description, color=color)
        embed.add_field(name="Score", value=f"You **{player_score}** — **{bot_score}** Angel", inline=True)
        embed.add_field(name="Rally", value=f"✨ {rally}", inline=True)
        return await ctx.send(embed=embed)

    await send_embed(
        "*A halo spins between you and the celestial guardian…*\n\n"
        "Type a number **1–5** to deflect the halo!\n"
        "Match within **±2** of the angel to keep the rally alive.\n"
        "First to **3 points** wins! You have **15 seconds** per deflection."
    )

    def check(m):
        return (
            m.author == ctx.author
            and m.channel == ctx.channel
            and m.content.isdigit()
            and 1 <= int(m.content) <= 5
        )

    try:
        while player_score < 3 and bot_score < 3:
            bot_val = random.randint(1, 5)
            try:
                msg = await bot.wait_for("message", timeout=15.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏰ *You hesitated… the halo falls. Angel scores!*")
                bot_score += 1
                rally = 0
                continue

            player_val = int(msg.content)
            diff = abs(player_val - bot_val)

            if diff <= 2:
                rally += 1
                desc = (
                    f"*You deflected **{player_val}**, the angel returned **{bot_val}**!*\n"
                    f"✨ Rally continues! Type another number 1–5."
                )
                await send_embed(desc, color=0x57F287)
            else:
                if player_val > bot_val:
                    bot_score += 1
                    desc = (
                        f"*You swung **{player_val}** but the angel sent **{bot_val}**…*\n"
                        f"🌑 The halo slipped past you! Angel scores!"
                    )
                else:
                    player_score += 1
                    desc = (
                        f"*You sent **{player_val}**, angel fumbled **{bot_val}**!*\n"
                        f"😇 You scored a point!"
                    )
                rally = 0
                await send_embed(desc, color=0xFFD700)

        if player_score >= 3:
            add_win(ctx.guild.id, ctx.author.id)
            edict_done = complete_edict(ctx.guild.id, ctx.author.id, "halo")
            result = f"🎉 {flavor(ANGEL_WIN)} **You won the Halo Duel!**"
            if edict_done:
                result += "\n📜 **Daily Edict fulfilled! 🔥**"
            color = 0x57F287
        else:
            result = f"😈 {flavor(ANGEL_LOSE)} **The angel wins this duel!**"
            color = 0xED4245

        embed = discord.Embed(title="😇 Duel Over!", description=result, color=color)
        embed.add_field(name="Final Score", value=f"You **{player_score}** — **{bot_score}** Angel", inline=False)
        await ctx.send(embed=embed)

    finally:
        active_pong.pop(ctx.channel.id, None)


# ── ✝️ Battle of Sigils (Tic-Tac-Toe) ─────────────────────────────────────────
TTT_EMPTY = "⬜"
TTT_X = "😇"   # player = holy angel
TTT_O = "😈"   # bot    = fallen angel


def ttt_board_str(board):
    rows = []
    for i in range(0, 9, 3):
        rows.append("".join(board[i:i+3]))
    return "\n".join(rows)


def ttt_check_winner(board):
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a, b, c in wins:
        if board[a] == board[b] == board[c] != TTT_EMPTY:
            return board[a]
    return None


def ttt_bot_move(board):
    def find_move(mark):
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a, b, c in wins:
            combo = [board[a], board[b], board[c]]
            if combo.count(mark) == 2 and combo.count(TTT_EMPTY) == 1:
                return [a, b, c][combo.index(TTT_EMPTY)]
        return None

    move = find_move(TTT_O) or find_move(TTT_X)
    if move is not None:
        return move
    if board[4] == TTT_EMPTY:
        return 4
    empty = [i for i, v in enumerate(board) if v == TTT_EMPTY]
    return random.choice(empty) if empty else None


@bot.command(name="sigil", help="Play Battle of Sigils (Tic-Tac-Toe)! Usage: !sigil")
async def sigil(ctx):
    if ctx.channel.id in active_ttt:
        await ctx.send("😇 *A sigil battle is already in progress here!*")
        return

    board = [TTT_EMPTY] * 9
    active_ttt[ctx.channel.id] = board
    NUMBER_MAP = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6, "8": 7, "9": 8}

    async def send_board(extra=""):
        embed = discord.Embed(
            title="✝️ Battle of Sigils",
            description=(
                f"*You are the Holy ({TTT_X}), the fallen oppose you ({TTT_O}).*\n\n"
                f"{ttt_board_str(board)}\n\n{extra}"
            ),
            color=0xF0C040,
        )
        embed.add_field(name="Position Guide", value="```\n1 2 3\n4 5 6\n7 8 9\n```", inline=False)
        embed.set_footer(text="Type a number 1–9 to place your sigil!")
        return await ctx.send(embed=embed)

    await send_board("*The heavens hold their breath… make your first move.*")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content in NUMBER_MAP

    try:
        while True:
            try:
                msg = await bot.wait_for("message", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏰ *You hesitated too long… the fallen claim victory by default.*")
                break

            idx = NUMBER_MAP[msg.content]
            if board[idx] != TTT_EMPTY:
                await ctx.send("❌ *That sigil is already claimed!* Choose another.")
                continue

            board[idx] = TTT_X
            winner = ttt_check_winner(board)
            if winner == TTT_X:
                add_win(ctx.guild.id, ctx.author.id)
                edict_done = complete_edict(ctx.guild.id, ctx.author.id, "sigil")
                result = f"🎉 {flavor(ANGEL_WIN)} **The holy sigils claim the board!**"
                if edict_done:
                    result += "\n📜 **Daily Edict fulfilled! 🔥**"
                await send_board(result)
                break

            if TTT_EMPTY not in board:
                await send_board(f"🌓 {flavor(ANGEL_TIE)} **The board is full — a draw!**")
                break

            bot_idx = ttt_bot_move(board)
            if bot_idx is not None:
                board[bot_idx] = TTT_O

            winner = ttt_check_winner(board)
            if winner == TTT_X:
                add_win(ctx.guild.id, ctx.author.id)
                edict_done = complete_edict(ctx.guild.id, ctx.author.id, "sigil")
                result = f"🎉 {flavor(ANGEL_WIN)} **The holy sigils claim the board!**"
                if edict_done:
                    result += "\n📜 **Daily Edict fulfilled! 🔥**"
                await send_board(result)
                break
            if winner == TTT_O:
                await send_board(f"😈 {flavor(ANGEL_LOSE)} **The fallen consume the board!**")
                break

            if TTT_EMPTY not in board:
                await send_board(f"🌓 {flavor(ANGEL_TIE)} **The board is full — a draw!**")
                break

            await send_board("*The fallen have moved… your turn.*")

    finally:
        active_ttt.pop(ctx.channel.id, None)


# ── 🔤 Sacred Scroll Search (Word Search) ─────────────────────────────────────
WORD_POOL = [
    # Celestial / angel themed
    "HALO", "WING", "ANGEL", "SERAPH", "DIVINE", "GRACE", "LIGHT",
    "ASCEND", "FALLEN", "FEATHER", "HEAVEN", "SACRED", "HOLY", "CHOIR",
    "SIGIL", "AURA", "GLORY", "HERALD", "THRONE", "VIRTUE", "RADIANT",
    "CELESTIAL", "ETHEREAL", "SANCTUM", "BLESSED", "ETERNAL", "CHOSEN",
    "RAPTURE", "EXALTED", "HERALD", "NIMBUS", "CHERUB", "PRAYER",
    "DEVOTED", "ASCENT", "PURITY", "ANOINTED", "CROWNED", "HALLOWED",
    "WISDOM", "GOSPEL", "LAMENT", "REBORN", "REFUGE", "ABSOLVED",
    "HYMN", "FAITH", "VEIL", "OATH", "SOUL", "HAZE", "GLOW", "DAWN",
    "DUSK", "MIST", "VOID", "RELIC", "CREST", "OMEN", "WRATH",
    # General / fantasy
    "SWORD", "STORM", "CROWN", "SHADOW", "FLAME", "CRYSTAL", "EMBER",
    "RAVEN", "SILVER", "GOLDEN", "MYSTIC", "ARCANE", "VALOR", "NOBLE",
    "SPIRIT", "DREAM", "PORTAL", "ANCIENT", "POWER", "MORTAL",
    "BLADE", "FORGE", "CRYPT", "DAGGER", "MANOR", "TOWER", "STAFF",
    "CLOAK", "ROGUE", "TITAN", "CHAOS", "ORDER", "VENOM", "FROST",
    "BLAZE", "GLYPH", "CURSE", "BLOOD", "EXILE", "WRAITH", "SHIELD",
    "ARROW", "SPIRE", "VAULT", "NEXUS", "SHARD", "RIFT", "ECHO",
    "FORGE", "CLASH", "REIGN", "REALM", "COVEN", "ABYSS", "RUIN",
    "SIEGE", "RIDGE", "BLIGHT", "THORN", "SHROUD", "STONE", "IRON",
    "COBRA", "RAVEN", "DRAKE", "WYRM", "INFERNO", "ORACLE", "FABLE",
    "GHOST", "DEMON", "DIVINE", "LUNAR", "ASTRAL", "COSMIC", "SIREN",
    "STORM", "KNIGHT", "RANGER", "DRUID", "WIZARD", "PALADIN", "ARCHER",
]
# Deduplicate while preserving order
WORD_POOL = list(dict.fromkeys(WORD_POOL))

# Track recently used words per guild to avoid repetition
recent_words: dict[int, list[str]] = defaultdict(list)
RECENT_MEMORY = 24  # avoid repeating any of the last 24 used words

GRID_SIZE = 10
DIRECTIONS = [
    (0, 1), (1, 0), (1, 1), (1, -1),   # right, down, diag-right, diag-left
    (0, -1), (-1, 0), (-1, -1), (-1, 1) # left, up, reverse diags
]

active_wordsearch: dict[int, dict] = {}  # channel_id -> game state

# Store word placements: {word: (start_r, start_c, dr, dc)}
WordPlacement = tuple[int, int, int, int]


def build_grid(words: list[str]) -> tuple[list[list[str]], dict[str, WordPlacement]]:
    """Place words in a grid. Returns grid and placement map."""
    grid = [["·"] * GRID_SIZE for _ in range(GRID_SIZE)]
    placements: dict[str, WordPlacement] = {}

    for word in words:
        dirs = DIRECTIONS[:]
        random.shuffle(dirs)
        positions = [(r, c) for r in range(GRID_SIZE) for c in range(GRID_SIZE)]
        random.shuffle(positions)
        success = False
        for dr, dc in dirs:
            for r, c in positions:
                end_r = r + dr * (len(word) - 1)
                end_c = c + dc * (len(word) - 1)
                if not (0 <= end_r < GRID_SIZE and 0 <= end_c < GRID_SIZE):
                    continue
                valid = True
                for i, letter in enumerate(word):
                    gr, gc = r + dr * i, c + dc * i
                    if grid[gr][gc] not in ("·", letter):
                        valid = False
                        break
                if valid:
                    for i, letter in enumerate(word):
                        gr, gc = r + dr * i, c + dc * i
                        grid[gr][gc] = letter
                    placements[word] = (r, c, dr, dc)
                    success = True
                    break
            if success:
                break

    # Fill empty cells
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            if grid[r][c] == "·":
                grid[r][c] = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    return grid, placements


def get_all_cells(placements: dict[str, WordPlacement]) -> dict[tuple[int,int], set[str]]:
    """Map every grid cell to the set of words that use it."""
    cell_words: dict[tuple[int,int], set[str]] = {}
    for word, (r, c, dr, dc) in placements.items():
        for i in range(len(word)):
            key = (r + dr * i, c + dc * i)
            cell_words.setdefault(key, set()).add(word)
    return cell_words


def render_grid(grid: list[list[str]], placements: dict[str, WordPlacement] = None, found: set[str] = None) -> str:
    """Render grid. Found-only cells show as [X], shared cells stay as plain letters."""
    found = found or set()
    placements = placements or {}

    cell_words = get_all_cells(placements)

    header = "`    ` " + " ".join(f"`{i+1:2}`" for i in range(GRID_SIZE))
    rows = [header]
    for r in range(GRID_SIZE):
        label = f"`{chr(65+r)}   `"
        cells = []
        for c in range(GRID_SIZE):
            letter = grid[r][c]
            words_here = cell_words.get((r, c), set())
            if words_here and words_here.issubset(found):
                # All words using this cell are found — show brackets
                cells.append(f"`[{letter}]`")
            else:
                # Hidden or shared — show plain letter
                cells.append(f"` {letter} `")
        rows.append(label + " " + " ".join(cells))
    return "\n".join(rows)


def coords_to_word(grid: list[list[str]], text: str, placements: dict[str, WordPlacement]) -> str | None:
    """
    Parse coordinate input like 'A3 A7' or 'A3-A7' and extract the word from the grid.
    Returns the matched placed word or None.
    """
    text = text.upper().replace("-", " ").replace("TO", " ")
    parts = text.split()
    if len(parts) != 2:
        return None

    def parse_coord(s):
        if len(s) < 2:
            return None
        row_char = s[0]
        col_str  = s[1:]
        if not row_char.isalpha() or not col_str.isdigit():
            return None
        r = ord(row_char) - ord('A')
        c = int(col_str) - 1
        if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
            return r, c
        return None

    start = parse_coord(parts[0])
    end   = parse_coord(parts[1])
    if not start or not end:
        return None

    sr, sc = start
    er, ec = end
    dr = 0 if er == sr else (1 if er > sr else -1)
    dc = 0 if ec == sc else (1 if ec > sc else -1)

    # Read letters along the line
    letters = []
    r, c = sr, sc
    while 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
        letters.append(grid[r][c])
        if (r, c) == (er, ec):
            break
        r += dr
        c += dc
    else:
        return None

    word = "".join(letters)
    # Check forward and backward
    for candidate in (word, word[::-1]):
        if candidate in placements:
            return candidate
    return None


@bot.command(name="wordsearch", aliases=["ws"], help="Play Sacred Scroll Search! Usage: !wordsearch")
async def wordsearch(ctx):
    if ctx.channel.id in active_wordsearch:
        await ctx.send("📜 *A sacred scroll is already open in this channel!*")
        return

    pool = WORD_POOL[:]
    random.shuffle(pool)
    used_recently = set(recent_words[ctx.guild.id])
    # Prefer words not used recently, fall back to full pool if needed
    fresh = [w for w in pool if w not in used_recently and 4 <= len(w) <= 8]
    stale = [w for w in pool if w in used_recently and 4 <= len(w) <= 8]
    candidates = (fresh + stale)[:8]

    grid, placements = build_grid(candidates)
    placed_words = list(placements.keys())

    if not placed_words:
        await ctx.send("❌ *The Scroll could not be inscribed. Try again.*")
        return

    # Record used words for this guild
    recent_words[ctx.guild.id].extend(placed_words)
    recent_words[ctx.guild.id] = recent_words[ctx.guild.id][-RECENT_MEMORY:]

    found: set[str] = set()
    active_wordsearch[ctx.channel.id] = {
        "grid": grid,
        "placements": placements,
        "words": placed_words,
        "found": found,
    }

    def make_embed(extra: str = "") -> discord.Embed:
        found_list  = " • ".join(f"~~{w}~~" for w in placed_words if w in found) or "none yet"
        remaining_count = len(placed_words) - len(found)
        embed = discord.Embed(
            title="📜 Sacred Scroll Search",
            description=(
                f"*The Eternal Scroll unfurls… hidden words lie within.*\n"
                f"*Scan the grid — no hints, only your eyes.*\n\n"
                f"{render_grid(grid, placements, found)}\n\n{extra}"
            ),
            color=0xF0C040,
        )
        embed.add_field(
            name="Words remaining",
            value=f"**{remaining_count}** hidden word{'s' if remaining_count != 1 else ''} still in the scroll",
            inline=True,
        )
        embed.add_field(name="Found so far", value=found_list, inline=True)
        embed.set_footer(
            text="Type the word • or coordinates e.g. A3 A7 • type 'give up' to reveal all"
        )
        return embed

    await ctx.send(embed=make_embed("*Search the grid and name what you find!*"))

    def check(m):
        if m.channel != ctx.channel or m.author.bot:
            return False
        content = m.content.strip()
        if content.lower() in ("give up", "!ws give up"):
            return True
        # Word match
        if content.upper() in [w for w in placed_words if w not in found]:
            return True
        # Coordinate match
        if coords_to_word(grid, content, placements):
            return True
        return False

    try:
        while len(found) < len(placed_words):
            try:
                msg = await bot.wait_for("message", timeout=300.0, check=check)
            except asyncio.TimeoutError:
                remaining = [w for w in placed_words if w not in found]
                await ctx.send(
                    f"⏰ *The Scroll seals itself after 5 minutes of silence.*\n"
                    f"The hidden words were: **{', '.join(remaining)}**"
                )
                break

            content = msg.content.strip()

            # Give up
            if content.lower() in ("give up", "!ws give up"):
                remaining = [w for w in placed_words if w not in found]
                await ctx.send(
                    f"🌑 *{msg.author.mention} surrenders to the darkness.*\n"
                    f"The remaining words were: **{', '.join(remaining)}**"
                )
                break

            # Resolve word — either typed directly or via coordinates
            word = content.upper() if content.upper() in placed_words else coords_to_word(grid, content, placements)
            if not word or word in found:
                continue

            found.add(word)
            add_win(ctx.guild.id, msg.author.id)
            edict_done = complete_edict(ctx.guild.id, msg.author.id, "wordsearch")

            if len(found) == len(placed_words):
                extra = (
                    f"✅ {msg.author.mention} found **{word}**!\n\n"
                    f"🎉 {flavor(ANGEL_WIN)} **All words found! The Scroll is complete!**"
                )
                if edict_done:
                    extra += "\n📜 **Daily Edict fulfilled! 🔥**"
                await ctx.send(embed=make_embed(extra))
            else:
                remaining_count = len(placed_words) - len(found)
                extra = (
                    f"✅ {msg.author.mention} found **{word}**! "
                    f"**{remaining_count}** word{'s' if remaining_count != 1 else ''} still hidden."
                )
                if edict_done:
                    extra += "\n📜 **Daily Edict fulfilled! 🔥**"
                await ctx.send(embed=make_embed(extra))

    finally:
        active_wordsearch.pop(ctx.channel.id, None)


# ── 🏆 The Ascendancy Rankings (Leaderboard) ──────────────────────────────────
@bot.command(name="ascendancy", help="View the Ascendancy Rankings (leaderboard).")
async def ascendancy(ctx):
    guild_scores = scores.get(ctx.guild.id)
    if not guild_scores:
        await ctx.send("📭 *The Ascendancy ledger is empty… prove yourself in the trials!*")
        return

    sorted_scores = sorted(guild_scores.items(), key=lambda x: x[1], reverse=True)
    medals = ["👑", "🥈", "🥉"]
    lines = []
    for i, (uid, wins) in enumerate(sorted_scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else "Unknown Soul"
        medal = medals[i] if i < 3 else f"**#{i+1}**"
        streak = streaks[ctx.guild.id][uid]["streak"]
        streak_str = f" 🔥{streak}" if streak > 1 else ""
        lines.append(f"{medal} {name} — **{wins}** {'victory' if wins == 1 else 'victories'}{streak_str}")

    embed = discord.Embed(
        title="👑 The Ascendancy Rankings",
        description="\n".join(lines),
        color=0xFFD700,
    )
    embed.set_footer(text=f"{ctx.guild.name} • Victories across all celestial trials")
    await ctx.send(embed=embed)


# ── 🌿 Sanctum Help ────────────────────────────────────────────────────────────
@bot.command(name="sanctum", help="Show all commands.")
async def sanctum(ctx):
    embed = discord.Embed(
        title="🪶 Welcome to the Angelic",
        description=(
            "*You stand between the holy and the fallen, mortal.*\n"
            "*The angels offer you their trials. Will you ascend?*"
        ),
        color=0xF0C040,
    )
    commands_list = [
        ("📜 `!edict`",        "See today's Daily Edict & your streak"),
        ("📜 `!prophecy`",     "Answer a Prophecy of the Eternal Scroll (Trivia)"),
        ("⚔️ `!trial`",       "Enter the Trial of Dominion (Rock Paper Scissors)"),
        ("🎲 `!cast`",         "Cast the Dice of Fate (Dice Roll)"),
        ("😇 `!halo`",         "Enter the Halo Deflection Duel (Pong)"),
        ("✝️ `!sigil`",       "Fight the Battle of Sigils (Tic-Tac-Toe)"),
        ("✨ `!divine`",       "Seek Divine Guidance (Magic 8-Ball)"),
        ("📜 `!wordsearch`",   "Sacred Scroll Search (Word Search) — also `!ws`"),
        ("👑 `!ascendancy`",   "View the Ascendancy Rankings (Leaderboard)"),
        ("🪶 `!feathers`",     "Feather Counter — count together, don't falter"),
    ]
    for name, value in commands_list:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="Complete the Daily Edict to grow your streak! 🔥")
    await ctx.send(embed=embed)


# ── 🪶 Feather Counter events & logic ─────────────────────────────────────────
SAVE_FILES = {
    "count_state":  "count_state.json",
    "scores":       "scores.json",
    "streaks":      "streaks.json",
    "count_board":  "count_board.json",
}


def save_all():
    """Save all persistent data to disk."""
    _save_count_state()
    _save_scores()
    _save_streaks()
    _save_count_board()


def _save_count_state():
    try:
        data = {
            str(gid): {
                "channel_id":   cs["channel_id"],
                "count":        cs["count"],
                "last_user_id": cs["last_user_id"],
                "high_score":   cs["high_score"],
                "shame_role":   cs.get("shame_role"),
            }
            for gid, cs in count_state.items()
        }
        with open(SAVE_FILES["count_state"], "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[save_count_state] {e}")

def save_count_state(): _save_count_state()  # alias used inline


def _save_scores():
    try:
        data = {str(gid): {str(uid): w for uid, w in users.items()}
                for gid, users in scores.items()}
        with open(SAVE_FILES["scores"], "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[save_scores] {e}")


def _save_streaks():
    try:
        data = {
            str(gid): {
                str(uid): s
                for uid, s in users.items()
            }
            for gid, users in streaks.items()
        }
        with open(SAVE_FILES["streaks"], "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[save_streaks] {e}")


def _save_count_board():
    try:
        data = {
            str(gid): {str(uid): d for uid, d in users.items()}
            for gid, users in count_board.items()
        }
        with open(SAVE_FILES["count_board"], "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[save_count_board] {e}")


def load_all():
    """Load all persistent data from disk on startup."""
    _load_count_state()
    _load_scores()
    _load_streaks()
    _load_count_board()


def _load_count_state():
    path = SAVE_FILES["count_state"]
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        for gid_str, cs in data.items():
            count_state[int(gid_str)] = {
                "channel_id":   cs["channel_id"],
                "count":        cs["count"],
                "last_user_id": cs["last_user_id"],
                "high_score":   cs["high_score"],
                "shame_role":   cs.get("shame_role"),
            }
        print(f"[load] count_state: {len(count_state)} guild(s)")
    except Exception as e:
        print(f"[load_count_state] {e}")


def _load_scores():
    path = SAVE_FILES["scores"]
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        for gid_str, users in data.items():
            for uid_str, wins in users.items():
                scores[int(gid_str)][int(uid_str)] = wins
        print(f"[load] scores: {sum(len(v) for v in scores.values())} entries")
    except Exception as e:
        print(f"[load_scores] {e}")


def _load_streaks():
    path = SAVE_FILES["streaks"]
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        for gid_str, users in data.items():
            for uid_str, s in users.items():
                streaks[int(gid_str)][int(uid_str)] = s
        print(f"[load] streaks: {sum(len(v) for v in streaks.values())} entries")
    except Exception as e:
        print(f"[load_streaks] {e}")


def _load_count_board():
    path = SAVE_FILES["count_board"]
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        for gid_str, users in data.items():
            for uid_str, d in users.items():
                count_board[int(gid_str)][int(uid_str)] = d
        print(f"[load] count_board: {sum(len(v) for v in count_board.values())} entries")
    except Exception as e:
        print(f"[load_count_board] {e}")


@bot.event
async def on_ready():
    load_all()
    print(f"🪶 The Angelic is online! Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game("!sanctum • The Angelic"))
    autosave.start()


@bot.event
async def on_error(event: str, *args, **kwargs):
    import traceback
    print(f"[on_error] unhandled error in {event}:")
    traceback.print_exc()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # ignore unknown commands silently
    else:
        import traceback
        print(f"[on_command_error] {ctx.command}: {error}")
        traceback.print_exc()


@tasks.loop(minutes=10)
async def autosave():
    """Save all data every 10 minutes automatically."""
    save_all()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return
    if message.guild:
        cs = count_state.get(message.guild.id)
        if cs and message.channel.id == cs["channel_id"] and not message.content.startswith("!"):
            try:
                await _handle_count(message, cs)
            except Exception as e:
                print(f"[on_message] counting error in guild {message.guild.id}: {e}")
                log_feathers(message.guild.id, f"❌ Unhandled error: `{e}`")
            return
    await bot.process_commands(message)


async def _handle_count(message: discord.Message, cs: dict):
    content = message.content.strip()

    # Normalize unicode digits (e.g. １２３ → 123)
    content = content.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

    if not content.isdigit():
        try:
            await message.add_reaction("❌")
        except Exception:
            pass
        await _count_ruin(message, cs, "non-number")
        return
    number = int(content)
    if number != cs["count"] + 1:
        try:
            await message.add_reaction("❌")
        except Exception:
            pass
        await _count_ruin(message, cs, "wrong-number")
        return
    if message.author.id == cs["last_user_id"]:
        try:
            await message.add_reaction("⚠️")
        except Exception:
            pass
        await _count_ruin(message, cs, "double-count")
        return
    cs["count"] += 1
    cs["last_user_id"] = message.author.id
    if cs["count"] > cs["high_score"]:
        cs["high_score"] = cs["count"]
    count_board[message.guild.id][message.author.id]["counts"] += 1
    log_feathers(message.guild.id, f"✅ {message.author.display_name} counted → **{cs['count']}**")
    c = cs["count"]
    if c % 10 == 0:
        save_count_state()
        _save_count_board()
    if c in COUNT_MILESTONES:
        try:
            await message.add_reaction("🎉")
        except Exception:
            pass
        try:
            await message.channel.send(COUNT_MILESTONE_MSGS[c])
        except Exception:
            pass
    elif c % 10 == 0:
        try:
            await message.add_reaction("🔥")
        except Exception:
            pass
    else:
        try:
            await message.add_reaction("🪶")
        except Exception:
            pass


async def _count_ruin(message: discord.Message, cs: dict, reason: str):
    old = cs["count"]
    cs["count"] = 0
    cs["last_user_id"] = None
    count_board[message.guild.id][message.author.id]["ruins"] += 1
    log_feathers(message.guild.id, f"💀 {message.author.display_name} ruined at **{old}** ({reason})")
    save_count_state()
    _save_count_board()
    shame_role = None
    if cs.get("shame_role") and message.guild:
        shame_role = discord.utils.get(message.guild.roles, name=cs["shame_role"])
        if shame_role:
            try:
                for m in message.guild.members:
                    if shame_role in m.roles and m.id != message.author.id:
                        await m.remove_roles(shame_role)
                await message.author.add_roles(shame_role)
            except discord.Forbidden:
                err = "missing Manage Roles permission"
                print(f"[_count_ruin] {err} in guild {message.guild.id}")
                log_feathers(message.guild.id, f"⚠️ Shame role error: `{err}`")
            except Exception as e:
                print(f"[_count_ruin] shame role error: {e}")
                log_feathers(message.guild.id, f"⚠️ Shame role error: `{e}`")
    reason_text = {
        "non-number":   "spoke impure words in the sacred count",
        "wrong-number": "miscounted the fallen feathers",
        "double-count": "tried to count twice — greedy soul",
    }.get(reason, "disrupted the sacred count")
    role_str = shame_role.mention if shame_role else "**The Fallen**"
    try:
        await message.channel.send(
            f"💀 {message.author.mention} {reason_text}!\n"
            f"*The count resets from **{old}** back to zero.*\n"
            f"{role_str} has been bestowed upon this soul. 😈"
        )
    except Exception as e:
        print(f"[_count_ruin] failed to send ruin message: {e}")


# ── 🪶 Feather Counter commands ────────────────────────────────────────────────
@bot.group(name="feathers", invoke_without_command=True)
@commands.has_permissions(manage_channels=True)
async def feathers_cmd(ctx):
    embed = discord.Embed(
        title="🪶 Feather Counter",
        description="Count fallen feathers together. Do not falter.",
        color=0xF0C040,
    )
    for name, val in [
        ("`!feathers setup`",            "Make this channel the counting channel"),
        ("`!feathers shame <role>`",     "Set the shame role for those who falter"),
        ("`!feathers leaderboard`",      "Top counters & worst offenders"),
        ("`!feathers milestones`",       "List all milestone numbers"),
        ("`!feathers status`",           "Show current count & high score"),
        ("`!feathers report`",           "View recent activity log & error reports"),
        ("`!feathers blame`",            "Run a diagnostic crash report 😈"),
        ("`!feathers reset`",            "Manually reset the count"),
        ("`!feathers remove`",           "Stop watching this channel"),
    ]:
        embed.add_field(name=name, value=val, inline=False)
    await ctx.send(embed=embed)


@feathers_cmd.command(name="setup")
@commands.has_permissions(manage_channels=True)
async def feathers_setup(ctx):
    count_state[ctx.guild.id] = {
        "channel_id": ctx.channel.id, "count": 0,
        "last_user_id": None, "high_score": 0, "shame_role": None,
    }
    save_count_state()
    embed = discord.Embed(
        title="🪶 Feather Channel Set",
        description=(
            f"**#{ctx.channel.name}** is now the sacred feather channel.\n\n"
            "Count up from **1** — one number per message.\n"
            "The same soul cannot count twice in a row.\n"
            "A wrong number resets the count to **0**."
        ),
        color=0xF0C040,
    )
    embed.add_field(name="Next step", value="Set a shame role with `!feathers shame The Fallen`", inline=False)
    await ctx.send(embed=embed)


@feathers_cmd.command(name="shame")
@commands.has_permissions(manage_channels=True)
async def feathers_shame(ctx, *, role_name: str):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ Run `!feathers setup` first.")
        return
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role:
        await ctx.send(f"❌ No role named **{role_name}** found. Create it in Server Settings → Roles first.")
        return
    cs["shame_role"] = role_name
    save_count_state()
    await ctx.send(f"😈 Shame role set to {role.mention}. Those who falter will bear this mark.")


@feathers_cmd.command(name="status")
async def feathers_status(ctx):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ No feather channel set up. Use `!feathers setup`.")
        return
    channel = ctx.guild.get_channel(cs["channel_id"])
    next_m = next((m for m in sorted(COUNT_MILESTONES) if m > cs["count"]), None)
    embed = discord.Embed(title="🪶 Feather Counter Status", color=0xF0C040)
    embed.add_field(name="Current count", value=f"🪶 **{cs['count']}**",      inline=True)
    embed.add_field(name="High score",    value=f"👑 **{cs['high_score']}**", inline=True)
    embed.add_field(name="Channel",       value=channel.mention if channel else "unknown", inline=True)
    embed.add_field(name="Shame role",    value=cs.get("shame_role") or "not set", inline=True)
    if next_m:
        embed.add_field(name="Next milestone", value=f"✨ {next_m} ({next_m - cs['count']} to go)", inline=True)
    await ctx.send(embed=embed)


@feathers_cmd.command(name="leaderboard")
async def feathers_leaderboard(ctx):
    data = count_board.get(ctx.guild.id, {})
    if not data:
        await ctx.send("📭 No feather data yet — start counting!")
        return
    medals = ["🥇", "🥈", "🥉"]
    def fmt(items, key):
        lines = []
        for i, (uid, d) in enumerate(sorted(items, key=lambda x: x[1][key], reverse=True)[:5]):
            if d[key] == 0: continue
            m = ctx.guild.get_member(uid)
            lines.append(f"{medals[i] if i < 3 else f'#{i+1}'} {m.display_name if m else 'Unknown'} — **{d[key]}**")
        return "\n".join(lines) or "None yet"
    embed = discord.Embed(title="🪶 Feather Leaderboard", color=0xF0C040)
    embed.add_field(name="👑 Top Counters",   value=fmt(data.items(), "counts"), inline=False)
    embed.add_field(name="😈 Most Fallen",    value=fmt(data.items(), "ruins"),  inline=False)
    await ctx.send(embed=embed)


@feathers_cmd.command(name="milestones")
async def feathers_milestones(ctx):
    cs = count_state.get(ctx.guild.id)
    current = cs["count"] if cs else 0
    lines = [
        f"{'✅' if current >= m else '⬜'} **{m}** — {COUNT_MILESTONE_MSGS[m][:55]}…"
        for m in sorted(COUNT_MILESTONES)
    ]
    await ctx.send(embed=discord.Embed(
        title="🪶 Feather Milestones",
        description="\n".join(lines),
        color=0xF0C040,
    ))


@feathers_cmd.command(name="blame")
@commands.has_permissions(manage_channels=True)
async def feathers_blame(ctx):
    display = "CodeHacker360"

    # Try to find and tag them if they're in the server
    target = discord.utils.find(
        lambda m: m.name.lower() == "codehacker360" or m.display_name.lower() == "codehacker360",
        ctx.guild.members
    )
    mention = target.mention if target else f"**{display}**"

    fake_errors = [
        f"gateway timeout during role assignment for `{display}`",
        f"rate limit exceeded after rapid inputs from `{display}`",
        f"message cache corruption triggered by `{display}`'s message",
        f"illegal unicode sequence detected in message by `{display}`",
        f"counting state lock deadlock caused by `{display}`",
    ]

    embed = discord.Embed(
        title="🚨 Feather Counter Crash Report",
        description="*A critical anomaly has been detected in the sacred count.*",
        color=0xED4245,
    )
    embed.add_field(
        name="❌ Fatal error",
        value=f"`CountingStateException: {random.choice(fake_errors)}`",
        inline=False,
    )
    embed.add_field(
        name="Responsible party",
        value=f"{mention} — flagged as the origin of the disruption",
        inline=False,
    )
    embed.add_field(
        name="Impact",
        value="Counting halted • State corrupted • Manual reset required",
        inline=False,
    )
    embed.add_field(
        name="Trace",
        value=(
            "```\n"
            f"File: feather_counter.py, line 247, in _handle_count\n"
            f"    await verify_sequence(message, cs)\n"
            f"File: feather_counter.py, line 189, in verify_sequence\n"
            f"    raise CountingStateException(user_id={target.id if target else '??????'})\n"
            f"CountingStateException: sequence broken by {display}\n"
            "```"
        ),
        inline=False,
    )
    embed.set_footer(text="The Angelic Bot • Crash Report • This report has been logged.")
    await ctx.send(embed=embed)


@feathers_cmd.command(name="report")
@commands.has_permissions(manage_channels=True)
async def feathers_report(ctx):
    cs = count_state.get(ctx.guild.id)
    channel = ctx.guild.get_channel(cs["channel_id"]) if cs else None
    log = feathers_log.get(ctx.guild.id, [])

    embed = discord.Embed(title="🪶 Feather Counter Report", color=0xF0C040)

    if cs:
        embed.add_field(
            name="Current state",
            value=(
                f"Channel: {channel.mention if channel else '`unknown`'}\n"
                f"Count: **{cs['count']}** • High score: **{cs['high_score']}**\n"
                f"Last user ID: `{cs['last_user_id']}`\n"
                f"Shame role: `{cs.get('shame_role') or 'none'}`"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="Current state", value="❌ No feather channel set up.", inline=False)

    embed.add_field(
        name=f"Recent activity (last {len(log)} events)",
        value="\n".join(log[-10:]) if log else "*No activity recorded yet.*",
        inline=False,
    )
    embed.set_footer(text="Errors appear here if counting silently breaks.")
    await ctx.send(embed=embed)


@feathers_cmd.command(name="reset")
@commands.has_permissions(manage_channels=True)
async def feathers_reset(ctx):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ No feather channel set up.")
        return
    old = cs["count"]
    cs["count"] = 0
    cs["last_user_id"] = None
    save_count_state()
    await ctx.send(f"🔄 *The heavens reset the count from **{old}** to zero. Begin again from **1**.*")


@feathers_cmd.command(name="remove")
@commands.has_permissions(manage_channels=True)
async def feathers_remove(ctx):
    if ctx.guild.id not in count_state:
        await ctx.send("❌ No feather channel is set up on this server.")
        return
    del count_state[ctx.guild.id]
    save_count_state()
    await ctx.send("🪶 *The angels withdraw. This channel is no longer sacred counting grounds.*")


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise ValueError("Set the DISCORD_TOKEN environment variable.")
    bot.run(token)
