"""
✨ The Fae Realm Bot ✨
A fairy-themed Discord games + counting bot.

Games:
  !grove       - Show all commands (themed help)
  !decree      - Today's daily challenge & streak
  !riddle      - Trivia (Riddles of the Ancient Grove)
  !pact        - Rock Paper Scissors (Pact of Elements)
  !bones       - Dice roll (Bones of Fate)
  !wisp        - Pong (Will-o'-Wisp Duel)  [text-based]
  !rings       - Tic-Tac-Toe (Battle of the Rings)
  !oracle      - Magic 8-Ball (The Oracle Speaks)
  !court       - Leaderboard (The Fairy Court Rankings)

Moonrise Counter:
  !count setup              - Make this channel the counting channel
  !count shame <role name>  - Set the shame role for ruiners
  !count leaderboard        - Top counters & worst ruiners
  !count milestones         - List all milestone numbers
  !count status             - Show current count & high score
  !count reset              - Manually reset the count (admin)
"""

import discord
from discord.ext import commands, tasks
import random
import re
import aiohttp
import asyncio
import datetime
import json
from collections import defaultdict

# ── Bot setup ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ── Persistent state (in-memory; swap for a DB in production) ─────────────────
scores: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))   # guild -> user -> wins
streaks: dict[int, dict[int, dict]] = defaultdict(                           # guild -> user -> {streak, last_date}
    lambda: defaultdict(lambda: {"streak": 0, "last_date": None, "completed_today": False})
)
active_ttt: dict[int, dict] = {}   # channel_id -> game state
active_pong: dict[int, dict] = {}  # channel_id -> game state

# ── 🌙 Moonrise Counter state ──────────────────────────────────────────────────
# {guild_id: {"channel_id": int, "count": int, "last_user_id": int|None,
#             "high_score": int, "shame_role": str|None}}
count_state: dict[int, dict] = {}
count_board: dict[int, dict[int, dict]] = defaultdict(
    lambda: defaultdict(lambda: {"counts": 0, "ruins": 0})
)

COUNT_MILESTONES = {10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000}
COUNT_MILESTONE_MSGS = {
    10:    "🌿 *The grove stirs… ten moonrises have passed!*",
    25:    "✨ *The sprites are dancing — twenty-five moonrises!*",
    50:    "🍄 *The mushroom rings glow brighter… fifty moonrises!*",
    100:   "🌙 *The Fairy Court cheers! One hundred moonrises!*",
    250:   "🌸 *The moonflowers bloom — two hundred and fifty!*",
    500:   "👑 *Five hundred moonrises! The elder fae bow in respect.*",
    1000:  "🌟 **ONE THOUSAND MOONRISES! The Fae Realm trembles with joy!**",
    2500:  "🔮 **Two thousand five hundred… mortals, you are legendary.**",
    5000:  "🧚 **FIVE THOUSAND. The Fairy Court has never seen such devotion.**",
    10000: "✨🌙✨ **TEN THOUSAND MOONRISES. You have transcended mortality.** ✨🌙✨",
}


def add_win(guild_id: int, user_id: int, amount: int = 1):
    scores[guild_id][user_id] += amount


# ── Fae flavor text helpers ───────────────────────────────────────────────────
FAE_GREETINGS = [
    "The mushroom circle stirs…",
    "A shimmer in the air…",
    "The Fairy Court takes notice…",
    "Moonpetal dust settles…",
    "The ancient oak whispers…",
]

FAE_WIN = [
    "The fae rejoice! 🌸",
    "The Court smiles upon thee! ✨",
    "Even the sprites are impressed! 🍄",
    "The moonflowers bloom in your honor! 🌙",
]

FAE_LOSE = [
    "The fairies titter with mischief… 😈",
    "The Court is… amused. 🍃",
    "Perhaps next moonrise, mortal. 🌑",
    "The pixies have stolen your luck! 🧚",
]

FAE_TIE = [
    "The veil between worlds trembles — a draw! 🌫️",
    "Neither moon nor sun claims victory… 🌓",
    "The Fairy Court declares a stalemate! ⚖️",
]

def fae_flavor(lst): return random.choice(lst)


# ── Daily Decree (daily challenge + streaks) ──────────────────────────────────
DAILY_CHALLENGES = [
    {"task": "Win a game of **!pact** (Rock Paper Scissors)", "cmd": "pact"},
    {"task": "Answer a **!riddle** correctly", "cmd": "riddle"},
    {"task": "Win a game of **!rings** (Tic-Tac-Toe)", "cmd": "rings"},
    {"task": "Roll a **natural 20** with `!bones d20`", "cmd": "bones"},
    {"task": "Win a game of **!wisp** (Pong)", "cmd": "wisp"},
    {"task": "Ask the **!oracle** three questions", "cmd": "oracle"},
]

def get_today_challenge():
    today = datetime.date.today()
    idx = today.toordinal() % len(DAILY_CHALLENGES)
    return DAILY_CHALLENGES[idx]


@bot.command(name="decree", help="See today's Daily Decree and your streak.")
async def decree(ctx):
    challenge = get_today_challenge()
    user_data = streaks[ctx.guild.id][ctx.author.id]
    today = str(datetime.date.today())

    completed = user_data["completed_today"] and user_data["last_date"] == today
    streak = user_data["streak"]

    embed = discord.Embed(
        title="📜 The Fairy Court's Daily Decree",
        description=(
            f"*{fae_flavor(FAE_GREETINGS)}*\n\n"
            f"Today's mortal trial:\n> {challenge['task']}"
        ),
        color=0xB57BFF,
    )
    embed.add_field(
        name="Your Streak",
        value=f"🔥 **{streak}** day{'s' if streak != 1 else ''}",
        inline=True,
    )
    embed.add_field(
        name="Today's Status",
        value="✅ **Completed!**" if completed else "⏳ **Pending…**",
        inline=True,
    )
    embed.set_footer(text="Complete the decree to keep your streak alive! Resets at midnight.")
    await ctx.send(embed=embed)


def complete_decree(guild_id: int, user_id: int, cmd: str):
    """Call this when a user wins a game that matches today's decree."""
    challenge = get_today_challenge()
    if challenge["cmd"] != cmd:
        return False
    today = str(datetime.date.today())
    user_data = streaks[guild_id][user_id]
    if user_data["completed_today"] and user_data["last_date"] == today:
        return False  # already completed today

    yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
    if user_data["last_date"] == yesterday:
        user_data["streak"] += 1
    else:
        user_data["streak"] = 1

    user_data["last_date"] = today
    user_data["completed_today"] = True
    return True


# ── 🎲 Bones of Fate (Dice Roll) ──────────────────────────────────────────────
@bot.command(name="bones", help="Roll the Bones of Fate. Usage: !bones 2d6 or !bones d20")
async def bones(ctx, dice: str = "1d6"):
    match = re.fullmatch(r"(\d+)?d(\d+)", dice.lower())
    if not match:
        await ctx.send("❌ *The bones clatter confusedly.* Try `!bones 2d6` or `!bones d20`.")
        return

    num = int(match.group(1) or 1)
    sides = int(match.group(2))

    if not (1 <= num <= 100) or not (2 <= sides <= 1000):
        await ctx.send("❌ *The fae refuse such an unreasonable request.*")
        return

    rolls = [random.randint(1, sides) for _ in range(num)]
    total = sum(rolls)
    nat20 = sides == 20 and num == 1 and total == 20

    embed = discord.Embed(
        title="🦴 Bones of Fate",
        description=f"*{fae_flavor(FAE_GREETINGS)}*",
        color=0xFFD700 if nat20 else 0xC8A96E,
    )
    embed.add_field(name="Roll", value=f"`{dice}`", inline=True)
    embed.add_field(name="Result", value=f"**{total}**{'  🌟 NATURAL 20!' if nat20 else ''}", inline=True)
    if num > 1:
        embed.add_field(name="Breakdown", value=", ".join(str(r) for r in rolls), inline=False)
    embed.set_footer(text=f"Cast by {ctx.author.display_name}")

    if nat20:
        # Natural 20 completes the decree
        decree_done = complete_decree(ctx.guild.id, ctx.author.id, "bones")
        if decree_done:
            embed.add_field(
                name="📜 Decree Fulfilled!",
                value="The Fairy Court cheers! Your streak lives on! 🔥",
                inline=False,
            )
        add_win(ctx.guild.id, ctx.author.id)

    await ctx.send(embed=embed)


# ── ❓ Riddles of the Ancient Grove (Trivia) ───────────────────────────────────
@bot.command(name="riddle", help="Answer a riddle from the Ancient Grove.")
async def riddle(ctx):
    url = "https://opentdb.com/api.php?amount=1&type=multiple"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ *The Grove is silent… try again later.*")
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
        title="🌿 A Riddle from the Ancient Grove",
        description=f"*The elder tree speaks…*\n\n{q['question']}",
        color=0x57C97B,
    )
    embed.add_field(name="Choices", value=choices_text, inline=False)
    embed.add_field(name="Domain", value=q["category"], inline=True)
    embed.add_field(name="Difficulty", value=q["difficulty"].capitalize(), inline=True)
    embed.set_footer(text="Reply with A, B, C, or D within 30 seconds…")
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in letters

    try:
        msg = await bot.wait_for("message", timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send(f"⏰ *The Grove grows impatient.* The answer was **{correct_letter}. {correct}**.")
        return

    if msg.content.upper() == correct_letter:
        add_win(ctx.guild.id, ctx.author.id)
        decree_done = complete_decree(ctx.guild.id, ctx.author.id, "riddle")
        reply = f"✅ {fae_flavor(FAE_WIN)} {ctx.author.mention} answered correctly!"
        if decree_done:
            reply += "\n📜 **Daily Decree fulfilled! Streak extended! 🔥**"
        await ctx.send(reply)
    else:
        await ctx.send(f"❌ {fae_flavor(FAE_LOSE)} The answer was **{correct_letter}. {correct}**.")


# ── 🪨 Pact of Elements (Rock Paper Scissors) ─────────────────────────────────
PACT_CHOICES = {"stone": "🪨", "leaf": "🍃", "spark": "⚡"}
PACT_WINS    = {"stone": "spark", "leaf": "stone", "spark": "leaf"}
PACT_FLAVOR  = {
    "stone": "an ancient river stone", "leaf": "a living leaf",
    "spark": "a captured lightning spark",
}

@bot.command(name="pact", help="Make a Pact of Elements. Usage: !pact stone/leaf/spark")
async def pact(ctx, choice: str = ""):
    choice = choice.lower()
    if choice not in PACT_CHOICES:
        await ctx.send("❌ *Choose your element:* `stone`, `leaf`, or `spark`. Example: `!pact stone`")
        return

    bot_choice = random.choice(list(PACT_CHOICES))
    you_emoji  = PACT_CHOICES[choice]
    bot_emoji  = PACT_CHOICES[bot_choice]

    if choice == bot_choice:
        result, color = fae_flavor(FAE_TIE), 0xFFFF00
    elif PACT_WINS[choice] == bot_choice:
        result, color = fae_flavor(FAE_WIN), 0x57F287
        add_win(ctx.guild.id, ctx.author.id)
        decree_done = complete_decree(ctx.guild.id, ctx.author.id, "pact")
        if decree_done:
            result += "\n📜 **Daily Decree fulfilled! Streak extended! 🔥**"
    else:
        result, color = fae_flavor(FAE_LOSE), 0xED4245

    embed = discord.Embed(title="⚡ Pact of Elements", color=color)
    embed.add_field(name="You chose",     value=f"{you_emoji} {PACT_FLAVOR[choice].capitalize()}", inline=True)
    embed.add_field(name="The Court chose", value=f"{bot_emoji} {PACT_FLAVOR[bot_choice].capitalize()}", inline=True)
    embed.add_field(name="Verdict", value=result, inline=False)
    await ctx.send(embed=embed)


# ── 🔮 The Oracle (Magic 8-Ball) ──────────────────────────────────────────────
ORACLE_RESPONSES = [
    "The moonflowers say *yes*. 🌸",
    "The river stones have spoken — *it shall be so*. 🪨",
    "The sprites dance in agreement! ✨",
    "The ancient oak nods its branches. 🌳",
    "Even the fae elders believe this to be true. 🧝",
    "The mist clears… and shows *yes*. 🌫️",
    "The Court is… *uncertain*. Ask again at moonrise. 🌙",
    "The oracle's eye is clouded. *Try again.* 👁️",
    "The pixies are arguing about this one. 🧚",
    "The veil is too thick to see clearly. 🌑",
    "The night-blooms wither at the thought. 🥀",
    "The fairies shake their tiny heads. *No.* 🍃",
    "The Fairy Court forbids it. ⚔️",
    "The river runs cold — *do not pursue this path*. 🌊",
    "Even the most mischievous sprite says *nay*. 😈",
]

oracle_uses: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

@bot.command(name="oracle", help="Consult the Oracle. Usage: !oracle Will I win?")
async def oracle(ctx, *, question: str = ""):
    if not question:
        await ctx.send("❓ *Speak your question into the mist.* Example: `!oracle Will I win?`")
        return

    today = str(datetime.date.today())
    key = f"{ctx.guild.id}:{ctx.author.id}:{today}"
    oracle_uses[ctx.guild.id][ctx.author.id] = oracle_uses[ctx.guild.id].get(ctx.author.id, 0) + 1
    uses_today = oracle_uses[ctx.guild.id][ctx.author.id]

    answer = random.choice(ORACLE_RESPONSES)
    embed = discord.Embed(
        title="🔮 The Oracle Speaks",
        description=f"*A mortal dares to ask…*\n\n_{question}_",
        color=0x9B59B6,
    )
    embed.add_field(name="The Oracle reveals", value=answer, inline=False)

    if uses_today >= 3:
        decree_done = complete_decree(ctx.guild.id, ctx.author.id, "oracle")
        if decree_done:
            embed.add_field(
                name="📜 Decree Fulfilled!",
                value="Three questions asked. The Court is satisfied. 🔥",
                inline=False,
            )
    embed.set_footer(text=f"Questions asked today: {uses_today}")
    await ctx.send(embed=embed)


# ── 🏓 Will-o'-Wisp Duel (Text Pong) ──────────────────────────────────────────
#   Turn-based text pong: player types a number 1-5, bot does too.
#   If they match → rally continues. After 5 rallies player wins.
#   If they miss (differ by >2) → that side loses the point.
#   First to 3 points wins.

PONG_WIDTH = 5  # numbers 1-5

@bot.command(name="wisp", help="Play Will-o'-Wisp Duel (text Pong)! Usage: !wisp")
async def wisp(ctx):
    if ctx.channel.id in active_pong:
        await ctx.send("🌟 *A duel is already taking place in this channel!*")
        return

    active_pong[ctx.channel.id] = True
    player_score = 0
    bot_score = 0
    rally = 0

    async def send_pong_embed(description, color=0x7FDBFF):
        embed = discord.Embed(
            title="🌟 Will-o'-Wisp Duel",
            description=description,
            color=color,
        )
        embed.add_field(name="Score", value=f"You **{player_score}** — **{bot_score}** Fae", inline=True)
        embed.add_field(name="Rally", value=f"⚡ {rally}", inline=True)
        return await ctx.send(embed=embed)

    await send_pong_embed(
        "*The will-o'-wisp floats between you and the fae…*\n\n"
        "Type a number **1–5** to volley the wisp!\n"
        "Match within **±2** of the fae to keep the rally alive.\n"
        "First to **3 points** wins! You have **15 seconds** per volley."
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
                await ctx.send("⏰ *The wisp fades… you hesitated too long!*")
                bot_score += 1
                rally = 0
                continue

            player_val = int(msg.content)
            diff = abs(player_val - bot_val)

            if diff <= 2:
                rally += 1
                desc = (
                    f"*You volleyed **{player_val}**, the fae returned **{bot_val}**!*\n"
                    f"✨ Rally keeps going! Type another number 1–5."
                )
                await send_pong_embed(desc, color=0x57F287)
            else:
                if player_val > bot_val:
                    bot_score += 1
                    desc = (
                        f"*You swung **{player_val}** but the fae sent **{bot_val}**…*\n"
                        f"💨 The wisp slipped past you! Fae scores!"
                    )
                else:
                    player_score += 1
                    desc = (
                        f"*You sent **{player_val}**, fae fumbled **{bot_val}**!*\n"
                        f"🌟 You scored a point!"
                    )
                rally = 0
                await send_pong_embed(desc, color=0xFFD700)

        # Game over
        if player_score >= 3:
            add_win(ctx.guild.id, ctx.author.id)
            decree_done = complete_decree(ctx.guild.id, ctx.author.id, "wisp")
            result = f"🎉 {fae_flavor(FAE_WIN)} **You won the Wisp Duel!**"
            if decree_done:
                result += "\n📜 **Daily Decree fulfilled! 🔥**"
            color = 0x57F287
        else:
            result = f"😈 {fae_flavor(FAE_LOSE)} **The fae wins this duel!**"
            color = 0xED4245

        embed = discord.Embed(title="🌟 Duel Over!", description=result, color=color)
        embed.add_field(name="Final Score", value=f"You **{player_score}** — **{bot_score}** Fae", inline=False)
        await ctx.send(embed=embed)

    finally:
        active_pong.pop(ctx.channel.id, None)


# ── ⭕ Battle of the Rings (Tic-Tac-Toe) ──────────────────────────────────────
TTT_EMPTY = "🟪"
TTT_X = "🍄"  # player = mushroom rings
TTT_O = "🔥"  # bot    = fireflies


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
    """Simple AI: win > block > center > random."""
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


@bot.command(name="rings", help="Play Battle of the Rings (Tic-Tac-Toe)! Usage: !rings")
async def rings(ctx):
    if ctx.channel.id in active_ttt:
        await ctx.send("🍄 *A ring battle is already in progress here!*")
        return

    board = [TTT_EMPTY] * 9
    active_ttt[ctx.channel.id] = board

    NUMBER_MAP = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6, "8": 7, "9": 8}

    async def send_board(extra=""):
        pos_guide = "```\n1 2 3\n4 5 6\n7 8 9\n```"
        embed = discord.Embed(
            title="🍄 Battle of the Rings",
            description=(
                f"*You are the Mushroom Rings ({TTT_X}), the fae are the Fireflies ({TTT_O}).*\n\n"
                f"{ttt_board_str(board)}\n\n{extra}"
            ),
            color=0xB57BFF,
        )
        embed.add_field(name="Position Guide", value=pos_guide, inline=False)
        embed.set_footer(text="Type a number 1–9 to place your ring!")
        return await ctx.send(embed=embed)

    await send_board("*The fairy ring glows… make your first move!*")

    def check(m):
        return (
            m.author == ctx.author
            and m.channel == ctx.channel
            and m.content in NUMBER_MAP
        )

    try:
        while True:
            # Player turn
            try:
                msg = await bot.wait_for("message", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏰ *The mushroom rings wither… you took too long!*")
                break

            idx = NUMBER_MAP[msg.content]
            if board[idx] != TTT_EMPTY:
                await ctx.send("❌ *That spot is already claimed by the fae realm!* Choose another.")
                continue

            board[idx] = TTT_X
            winner = ttt_check_winner(board)
            if winner:
                add_win(ctx.guild.id, ctx.author.id)
                decree_done = complete_decree(ctx.guild.id, ctx.author.id, "rings")
                result = f"🎉 {fae_flavor(FAE_WIN)} **Your mushroom rings claim the grove!**"
                if decree_done:
                    result += "\n📜 **Daily Decree fulfilled! 🔥**"
                await send_board(result)
                break

            if TTT_EMPTY not in board:
                await send_board(f"🌓 {fae_flavor(FAE_TIE)} **The grove is full — a draw!**")
                break

            # Bot turn
            bot_idx = ttt_bot_move(board)
            if bot_idx is not None:
                board[bot_idx] = TTT_O

            winner = ttt_check_winner(board)
            if winner == TTT_X:
                add_win(ctx.guild.id, ctx.author.id)
                decree_done = complete_decree(ctx.guild.id, ctx.author.id, "rings")
                result = f"🎉 {fae_flavor(FAE_WIN)} **Your mushroom rings claim the grove!**"
                if decree_done:
                    result += "\n📜 **Daily Decree fulfilled! 🔥**"
                await send_board(result)
                break
            if winner == TTT_O:
                await send_board(f"😈 {fae_flavor(FAE_LOSE)} **The fireflies consume the grove!**")
                break

            if TTT_EMPTY not in board:
                await send_board(f"🌓 {fae_flavor(FAE_TIE)} **The grove is full — a draw!**")
                break

            await send_board("*The fae have moved… your turn, mortal.*")

    finally:
        active_ttt.pop(ctx.channel.id, None)


# ── 🏆 The Fairy Court Rankings (Leaderboard) ─────────────────────────────────
@bot.command(name="court", help="View the Fairy Court Rankings (leaderboard).")
async def court(ctx):
    guild_scores = scores.get(ctx.guild.id)
    if not guild_scores:
        await ctx.send("📭 *The Court's ledger is empty… play some games to earn your place!*")
        return

    sorted_scores = sorted(guild_scores.items(), key=lambda x: x[1], reverse=True)
    medals = ["👑", "🥈", "🥉"]
    lines = []
    for i, (uid, wins) in enumerate(sorted_scores[:10]):
        member = ctx.guild.get_member(uid)
        name = member.display_name if member else f"Unknown Mortal"
        medal = medals[i] if i < 3 else f"**#{i+1}**"
        streak = streaks[ctx.guild.id][uid]["streak"]
        streak_str = f" 🔥{streak}" if streak > 1 else ""
        lines.append(f"{medal} {name} — **{wins}** {'victory' if wins == 1 else 'victories'}{streak_str}")

    embed = discord.Embed(
        title="👑 The Fairy Court Rankings",
        description="\n".join(lines),
        color=0xFFD700,
    )
    embed.set_footer(text=f"{ctx.guild.name} • Victories across all fae trials")
    await ctx.send(embed=embed)


# ── 🌿 Grove Help ──────────────────────────────────────────────────────────────
@bot.command(name="grove", help="Show all commands.")
async def grove(ctx):
    embed = discord.Embed(
        title="🌿 Welcome to the Fae Realm",
        description=(
            "*You have stumbled into the Fairy Court, mortal.*\n"
            "*The fae offer you their trials. Will you prove yourself worthy?*"
        ),
        color=0x57C97B,
    )
    commands_list = [
        ("📜 `!decree`",  "See today's Daily Decree & your streak"),
        ("🌿 `!riddle`",  "Answer a Riddle of the Ancient Grove (Trivia)"),
        ("⚡ `!pact`",    "Make a Pact of Elements (Rock Paper Scissors)"),
        ("🦴 `!bones`",   "Cast the Bones of Fate (Dice Roll)"),
        ("🌟 `!wisp`",    "Enter a Will-o'-Wisp Duel (Pong)"),
        ("🍄 `!rings`",   "Fight the Battle of the Rings (Tic-Tac-Toe)"),
        ("🔮 `!oracle`",  "Consult the Oracle (Magic 8-Ball)"),
        ("👑 `!court`",   "View the Fairy Court Rankings (Leaderboard)"),
        ("🌙 `!count`",   "Moonrise Counter — count together, don't mess up"),
    ]
    for name, value in commands_list:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="Complete the Daily Decree to grow your streak! 🔥")
    await ctx.send(embed=embed)


# ── Run ────────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✨ The Fae Realm awakens! Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game("!grove • Enter the Fae Realm"))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return
    # Counting channel handler
    if message.guild:
        cs = count_state.get(message.guild.id)
        if cs and message.channel.id == cs["channel_id"] and not message.content.startswith("!"):
            await _handle_count(message, cs)
            return
    await bot.process_commands(message)


async def _handle_count(message: discord.Message, cs: dict):
    content = message.content.strip()
    if not content.isdigit():
        await message.add_reaction("❌")
        await _count_ruin(message, cs, "non-number")
        return
    number = int(content)
    expected = cs["count"] + 1
    if number != expected:
        await message.add_reaction("❌")
        await _count_ruin(message, cs, "wrong-number")
        return
    if message.author.id == cs["last_user_id"]:
        await message.add_reaction("⚠️")
        await _count_ruin(message, cs, "double-count")
        return
    # Valid count
    cs["count"] += 1
    cs["last_user_id"] = message.author.id
    if cs["count"] > cs["high_score"]:
        cs["high_score"] = cs["count"]
    count_board[message.guild.id][message.author.id]["counts"] += 1
    c = cs["count"]
    if c in COUNT_MILESTONES:
        await message.add_reaction("🎉")
        await message.channel.send(COUNT_MILESTONE_MSGS[c])
    elif c % 10 == 0:
        await message.add_reaction("🔥")
    else:
        await message.add_reaction("✅")


async def _count_ruin(message: discord.Message, cs: dict, reason: str):
    old = cs["count"]
    cs["count"] = 0
    cs["last_user_id"] = None
    count_board[message.guild.id][message.author.id]["ruins"] += 1
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
                pass
    reason_text = {
        "non-number":   "dared to speak non-numbers in the sacred grove",
        "wrong-number": "miscounted the moonrises",
        "double-count": "tried to count twice — greedy mortal",
    }.get(reason, "disrupted the count")
    role_str = shame_role.mention if shame_role else "**Ruiner of the Court**"
    await message.channel.send(
        f"💀 {message.author.mention} {reason_text}!\n"
        f"*The count resets from **{old}** back to zero.*\n"
        f"{role_str} has been bestowed upon this mortal. 🧚"
    )


# ── 🌙 Moonrise Counter commands ───────────────────────────────────────────────
@bot.group(name="count", invoke_without_command=True)
@commands.has_permissions(manage_channels=True)
async def count_cmd(ctx):
    embed = discord.Embed(
        title="🌙 Moonrise Counter",
        description="A fae-blessed counting channel. Count together. Don't mess up.",
        color=0x9B59B6,
    )
    for name, val in [
        ("`!count setup`",            "Make this channel the counting channel"),
        ("`!count shame <role>`",     "Set the shame role for ruiners"),
        ("`!count leaderboard`",      "Top counters & worst ruiners"),
        ("`!count milestones`",       "List all milestone numbers"),
        ("`!count status`",           "Show current count & high score"),
        ("`!count reset`",            "Manually reset the count"),
    ]:
        embed.add_field(name=name, value=val, inline=False)
    await ctx.send(embed=embed)


@count_cmd.command(name="setup")
@commands.has_permissions(manage_channels=True)
async def count_setup(ctx):
    count_state[ctx.guild.id] = {
        "channel_id": ctx.channel.id, "count": 0,
        "last_user_id": None, "high_score": 0, "shame_role": None,
    }
    embed = discord.Embed(
        title="🌙 Counting Channel Set",
        description=(
            f"**#{ctx.channel.name}** is now the sacred counting grove.\n\n"
            "Members count up from **1** — one number per message.\n"
            "The same person cannot count twice in a row.\n"
            "Wrong number resets the count to **0**."
        ),
        color=0x9B59B6,
    )
    embed.add_field(name="Next step", value="Set a shame role with `!count shame Ruiner of the Court`", inline=False)
    await ctx.send(embed=embed)


@count_cmd.command(name="shame")
@commands.has_permissions(manage_channels=True)
async def count_shame(ctx, *, role_name: str):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ Run `!count setup` first.")
        return
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role:
        await ctx.send(f"❌ No role named **{role_name}** found. Create it in Server Settings → Roles first.")
        return
    cs["shame_role"] = role_name
    await ctx.send(f"🎭 Shame role set to {role.mention}. Ruiners beware.")


@count_cmd.command(name="status")
async def count_status(ctx):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ No counting channel set up. Use `!count setup`.")
        return
    channel = ctx.guild.get_channel(cs["channel_id"])
    next_m = next((m for m in sorted(COUNT_MILESTONES) if m > cs["count"]), None)
    embed = discord.Embed(title="🌙 Moonrise Status", color=0x9B59B6)
    embed.add_field(name="Current count", value=f"🌙 **{cs['count']}**", inline=True)
    embed.add_field(name="High score",    value=f"🏆 **{cs['high_score']}**", inline=True)
    embed.add_field(name="Channel",       value=channel.mention if channel else "unknown", inline=True)
    embed.add_field(name="Shame role",    value=cs.get("shame_role") or "not set", inline=True)
    if next_m:
        embed.add_field(name="Next milestone", value=f"✨ {next_m} ({next_m - cs['count']} to go)", inline=True)
    await ctx.send(embed=embed)


@count_cmd.command(name="leaderboard")
async def count_leaderboard(ctx):
    data = count_board.get(ctx.guild.id, {})
    if not data:
        await ctx.send("📭 No counting data yet — start counting!")
        return
    medals = ["🥇", "🥈", "🥉"]
    def fmt(items, key):
        lines = []
        for i, (uid, d) in enumerate(sorted(items, key=lambda x: x[1][key], reverse=True)[:5]):
            if d[key] == 0: continue
            m = ctx.guild.get_member(uid)
            lines.append(f"{medals[i] if i < 3 else f'#{i+1}'} {m.display_name if m else 'Unknown'} — **{d[key]}**")
        return "\n".join(lines) or "None yet"
    embed = discord.Embed(title="🌙 Moonrise Leaderboard", color=0x9B59B6)
    embed.add_field(name="🏆 Top Counters",  value=fmt(data.items(), "counts"), inline=False)
    embed.add_field(name="💀 Worst Ruiners", value=fmt(data.items(), "ruins"),  inline=False)
    await ctx.send(embed=embed)


@count_cmd.command(name="milestones")
async def count_milestones(ctx):
    cs = count_state.get(ctx.guild.id)
    current = cs["count"] if cs else 0
    lines = [
        f"{'✅' if current >= m else '⬜'} **{m}** — {COUNT_MILESTONE_MSGS[m][:50]}…"
        for m in sorted(COUNT_MILESTONES)
    ]
    await ctx.send(embed=discord.Embed(
        title="🌙 Moonrise Milestones",
        description="\n".join(lines),
        color=0x9B59B6,
    ))


@count_cmd.command(name="reset")
@commands.has_permissions(manage_channels=True)
async def count_reset(ctx):
    cs = count_state.get(ctx.guild.id)
    if not cs:
        await ctx.send("❌ No counting channel set up.")
        return
    old = cs["count"]
    cs["count"] = 0
    cs["last_user_id"] = None
    await ctx.send(f"🔄 *The Fairy Court resets the count from **{old}** to zero. Begin again from **1**.*")


if __name__ == "__main__":
    import os
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise ValueError("Set the DISCORD_TOKEN environment variable.")
    bot.run(token)
