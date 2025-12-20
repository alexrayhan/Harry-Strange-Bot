from __future__ import annotations

import os
import json
import random
import asyncio
import re
from typing import Dict, Any

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
# -------- DUEL SYSTEM (PHASE A) --------

player_stats = {}  # user_id -> {"hp": int, "in_duel": bool}

active_duel = {
    "active": False,
    "player1": None,
    "player2": None,
    "turn": None,
    "challenged": None,
}
def init_player(user_id: int):
    if user_id not in player_stats:
        player_stats[user_id] = {
            "hp": 100,
            "charisma": 50,
            "shield": 0,
            "in_duel": False,
            "cooldowns": {}
        }
def _end_duel(winner: int, loser: int):
    for uid in (winner, loser):
        player_stats[uid]["in_duel"] = False

    active_duel.update({
        "active": False,
        "player1": None,
        "player2": None,
        "turn": None,
        "challenged": None,
    })
# ---------------- CONFIG ----------------
# Prefer env var. Replace the string below only for local/private testing (NOT for public repos)
TOKEN = os.environ.get("BOT_TOKEN") or "8214478922:AAEeLgZD3aUSKeN_voD-Aw7Eymd3Ow4bCHU"

DATA_FILE = "data.json"

HOUSES = ["Gryffindor", "Ravenclaw", "Hufflepuff", "Slytherin"]

# runtime data (populated by load_data_sync)
user_houses: Dict[int, str] = {}  # user_id -> house name
user_names: Dict[int, str] = {}  # user_id -> display name
house_points: Dict[str, int] = {h: 0 for h in HOUSES}
ADMIN_IDS: Dict[int, str] = {
    8021336166: "Shadow"
}
quiz_scores: Dict[int, int] = {}  # user_id -> quiz score
duel_wins: Dict[int, int] = {}

# lock for file writes (async)
data_lock = asyncio.Lock()

ADMINS = {
    8021336166,  # Shadow
}

# ----------------- UTIL -----------------
def escape_md(text: str) -> str:
    """Escape characters that break Telegram Markdown parsing."""
    if text is None:
        return ""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(text))


def _sync_read() -> Dict[str, Any]:
    """Synchronous file read (used inside load_data_sync)."""
    try:
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _sync_write(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def save_data() -> None:
    """Async wrapper to save runtime structures to disk."""
    async with data_lock:
        data = {
            "user_houses": {str(k): v for k, v in user_houses.items()},
            "user_names": {str(k): v for k, v in user_names.items()},
            "house_points": house_points,
            "ADMIN_IDS": {str(k): v for k, v in ADMIN_IDS.items()},
            "quiz_scores": {str(k): v for k, v in quiz_scores.items()},
            "duel_wins": {str(k): v for k, v in duel_wins.items()},
        }
        await asyncio.to_thread(_sync_write, data)


def load_data_sync() -> None:
    """Load from data.json synchronously at startup (no event loop created/closed)."""
    loaded = _sync_read()

    uh = {}
    for k, v in loaded.get("user_houses", {}).items():
        try:
            uh[int(k)] = v
        except Exception:
            pass
    user_houses.clear()
    user_houses.update(uh)

    un = {}
    for k, v in loaded.get("user_names", {}).items():
        try:
            un[int(k)] = v
        except Exception:
            pass
    user_names.clear()
    user_names.update(un)

    hp = loaded.get("house_points", {}) or {}
    for h in HOUSES:
        house_points[h] = int(hp.get(h, 0))

    adm = {}
    for k, v in loaded.get("ADMIN_IDS", {}).items():
        try:
            adm[int(k)] = v
        except Exception:
            pass
    ADMIN_IDS.clear()
    ADMIN_IDS.update(adm)

    qs = {}
    for k, v in loaded.get("quiz_scores", {}).items():
        try:
            qs[int(k)] = int(v)
        except Exception:
            pass
    quiz_scores.clear()
    quiz_scores.update(qs)

    dw = {}
    for k, v in loaded.get("duel_wins", {}).items():
        try:
            dw[int(k)] = int(v)
        except Exception:
            pass
    duel_wins.clear()
    duel_wins.update(dw)


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS


# --------------- HEALTH SERVER (small) ---------------
def _start_health_server():
    """Start a tiny HTTP server in a daemon thread so platforms expecting a web port don't kill the container."""
    try:
        import threading
        import http.server
        import socketserver

        port = int(os.environ.get("PORT") or os.environ.get("PORT0") or 8000)

        class SilentHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                return

        def _serve():
            try:
                with socketserver.TCPServer(("", port), SilentHandler) as httpd:
                    httpd.serve_forever()
            except Exception:
                pass

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        print(f"DEBUG: health server started on port {port}")
    except Exception as e:
        print("DEBUG: failed to start health server:", repr(e))

def start_turn(user_id: int):
    """Apply start-of-turn effects: charisma regen + cooldown reduction."""
    stats = player_stats[user_id]

    # Charisma regen
    stats["charisma"] = min(stats["charisma"] + 5, 100)

    # Reduce cooldowns
    to_remove = []
    for spell, cd in stats["cooldowns"].items():
        stats["cooldowns"][spell] -= 1
        if stats["cooldowns"][spell] <= 0:
            to_remove.append(spell)

    for spell in to_remove:
        del stats["cooldowns"][spell]

# ----------------- COMMAND HANDLERS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🏰 *Hogwarts House Point System*\n\n"
        "Commands:\n"
        "/sortme - get sorted into a house\n"
        "/whoami - see your house and stats\n"
        "/houseinfo - list members by house\n"
        "/points - show house points\n"
        "/leaderboard - show house leaderboard\n"
        "/quiz - take a quick quiz (reply with option number)\n\n"
        "Admin (professors) commands (reply to a user's message for some):\n"
        "/unsort, /resort <House>, /expelliarmus (mute), /stupefy (warn), /avadakedavra (ban)\n"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def sortme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if uid in user_houses:
        house = user_houses[uid]
        await update.message.reply_text(f"You are already in *{escape_md(house)}*", parse_mode="Markdown")
        return
    house = random.choice(HOUSES)
    user_houses[uid] = house
    user_names[uid] = user.username or (user.first_name or str(uid))
    await save_data()
    await update.message.reply_text(f"🎩 The Sorting Hat has chosen *{escape_md(house)}* for you!", parse_mode="Markdown")


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    house = user_houses.get(uid)
    name = user_names.get(uid, user.username or user.first_name or str(uid))
    name_esc = escape_md(name)
    if house:
        await update.message.reply_text(f"👤 {name_esc}\n🏠 *House:* {escape_md(house)}\n🏆 Quiz points: {quiz_scores.get(uid,0)}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"👤 {name_esc}\nYou are not sorted yet. Use /sortme.", parse_mode="Markdown")


async def houseinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = "🏰 *House Members* 🏰\n\n"
    for house in HOUSES:
        result += f"🎓 *{escape_md(house)}*\n"
        members = [uid for uid, h in user_houses.items() if h == house]
        if not members:
            result += "_No students yet._\n\n"
            continue
        for uid in members:
            name = escape_md(user_names.get(uid, str(uid)))
            result += f"• {name}\n"
        result += "\n"
    await update.message.reply_text(result, parse_mode="Markdown")


async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🏅 *House Points*"]
    for h in HOUSES:
        lines.append(f"{escape_md(h)} — {house_points.get(h,0)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin-only: /addpoints <house> <amount>
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Only admins can add points.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addpoints <house> <amount>")
        return
    house = context.args[0].capitalize()
    try:
        amount = int(context.args[1])
    except Exception:
        await update.message.reply_text("Amount must be integer.")
        return
    if house not in HOUSES:
        await update.message.reply_text("Invalid house.")
        return
    house_points[house] = house_points.get(house, 0) + amount
    await save_data()
    await update.message.reply_text(f"✅ Added {amount} points to {escape_md(house)}.", parse_mode="Markdown")


async def deductpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("🚫 Only admins can deduct points.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /deductpoints <house> <amount>")
        return
    house = context.args[0].capitalize()
    try:
        amount = int(context.args[1])
    except Exception:
        await update.message.reply_text("Amount must be integer.")
        return
    if house not in HOUSES:
        await update.message.reply_text("Invalid house.")
        return
    house_points[house] = max(0, house_points.get(house, 0) - amount)
    await save_data()
    await update.message.reply_text(f"✅ Deducted {amount} points from {escape_md(house)}.", parse_mode="Markdown")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_houses = sorted(house_points.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 *House Leaderboard* 🏆\n\n"
    for house, pts in sorted_houses:
        text += f"🏰 *{escape_md(house)}* — {pts} points\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    challenger = update.effective_user

    if active_duel["active"]:
        await update.message.reply_text("⚔️ A duel is already in progress. Wait your turn.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to challenge them.")
        return

    target = update.message.reply_to_message.from_user

    if target.id == challenger.id:
        await update.message.reply_text("You can’t duel yourself.")
        return

    init_player(challenger.id)
    init_player(target.id)

    active_duel.update({
        "active": False,
        "player1": challenger.id,
        "player2": target.id,
        "turn": None,
        "challenged": target.id,
    })

    await update.message.reply_text(
        f"⚔️ {challenger.first_name} challenges {target.first_name}!\n"
        f"{target.first_name}, type /accept or /decline."
    )

async def accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if active_duel["challenged"] != user.id:
        return

    p1 = active_duel["player1"]
    p2 = active_duel["player2"]

    # Reset stats
    player_stats[p1]["hp"] = 100
    player_stats[p2]["hp"] = 100
    player_stats[p1]["charisma"] = 50
    player_stats[p2]["charisma"] = 50
    player_stats[p1]["shield"] = 0
    player_stats[p2]["shield"] = 0
    player_stats[p1]["cooldowns"] = {}
    player_stats[p2]["cooldowns"] = {}
    player_stats[p1]["in_duel"] = True
    player_stats[p2]["in_duel"] = True

    # Activate duel
    active_duel.update({
        "active": True,
        "turn": p1,
        "challenged": None,
    })

    # 🔑 THIS IS THE IMPORTANT LINE
    start_turn(p1)

    challenger_name = user_names.get(p1, "Challenger")
    target_name = user.first_name

    await update.message.reply_text(
        f"🔥 *Duel Started!*\n\n"
        f"{escape_md(challenger_name)} ❤️100 ✨{player_stats[p1]['charisma']}\n"
        f"{escape_md(target_name)} ❤️100 ✨{player_stats[p2]['charisma']}\n\n"
        f"➡️ *{escape_md(challenger_name)}'s turn*\n"
        f"Use `/cast_stupefy`",
        parse_mode="Markdown"
    )

async def decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if active_duel["challenged"] != user.id:
        return

    active_duel.update({
        "active": False,
        "player1": None,
        "player2": None,
        "turn": None,
        "challenged": None,
    })

    await update.message.reply_text("❌ Duel declined.")

async def cast_stupefy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not active_duel["active"]:
        return

    if active_duel["turn"] != user.id:
        await update.message.reply_text("⏳ Not your turn.")
        return

    attacker = user.id
    defender = (
        active_duel["player2"]
        if attacker == active_duel["player1"]
        else active_duel["player1"]
    )

    attacker_stats = player_stats[attacker]
    defender_stats = player_stats[defender]

    # charisma check
    if attacker_stats["charisma"] < 10:
        await update.message.reply_text("✨ Not enough Charisma to cast Stupefy.")
        return

    # cost
    attacker_stats["charisma"] -= 10

    # damage logic (shield first)
    damage = 15
    if defender_stats["shield"] > 0:
        absorbed = min(defender_stats["shield"], damage)
        defender_stats["shield"] -= absorbed
        damage -= absorbed

    defender_stats["hp"] -= damage
    defender_hp = max(defender_stats["hp"], 0)

    attacker_name = user_names.get(attacker, user.first_name)
    defender_name = user_names.get(defender, "Opponent")

    # defeat check
    if defender_hp <= 0:
        await update.message.reply_text(
            f"💥 *{escape_md(attacker_name)}* casts **Stupefy!**\n"
            f"💀 *{escape_md(defender_name)}* has fallen!\n\n"
            f"🏆 *{escape_md(attacker_name)} wins the duel!*",
            parse_mode="Markdown"
        )

        for uid in (attacker, defender):
            player_stats[uid]["in_duel"] = False

        active_duel.update({
            "active": False,
            "player1": None,
            "player2": None,
            "turn": None,
            "challenged": None,
        })
        return

    # switch turn
    active_duel["turn"] = defender
    start_turn(defender)

    await update.message.reply_text(
        f"✨ *{escape_md(attacker_name)}* casts **Stupefy!**\n"
        f"{escape_md(defender_name)} ❤️{defender_hp}\n"
        f"✨ Charisma left: {attacker_stats['charisma']}\n\n"
        f"➡️ *{escape_md(defender_name)}'s turn*",
        parse_mode="Markdown"
    )
async def cast_crucio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not active_duel["active"]:
        return

    if active_duel["turn"] != user.id:
        await update.message.reply_text("⏳ Not your turn.")
        return

    attacker = user.id
    defender = (
        active_duel["player2"]
        if attacker == active_duel["player1"]
        else active_duel["player1"]
    )

    atk = player_stats[attacker]
    dfn = player_stats[defender]

    # Cooldown check
    if atk["cooldowns"].get("crucio", 0) > 0:
        await update.message.reply_text("⏳ Crucio is on cooldown.")
        return

    # Charisma check
    if atk["charisma"] < 30:
        await update.message.reply_text("✨ Not enough Charisma to cast Crucio.")
        return

    # Cost & cooldown
    atk["charisma"] -= 30
    atk["cooldowns"]["crucio"] = 2

    # Backlash
    atk["hp"] -= 5

    # Damage
    damage = 35
    if dfn["shield"] > 0:
        absorbed = min(dfn["shield"], damage)
        dfn["shield"] -= absorbed
        damage -= absorbed

    dfn["hp"] -= damage

    atk_name = user_names.get(attacker, user.first_name)
    dfn_name = user_names.get(defender, "Opponent")

    # Attacker death from backlash
    if atk["hp"] <= 0:
        await update.message.reply_text(
            f"🔥 *{escape_md(atk_name)}* casts **Crucio!**\n"
            f"💥 The curse backfires!\n"
            f"💀 *{escape_md(atk_name)}* collapses!\n\n"
            f"🏆 *{escape_md(dfn_name)} wins the duel!*",
            parse_mode="Markdown"
        )
        _end_duel(attacker, defender)
        return

    # Defender death
    if dfn["hp"] <= 0:
        await update.message.reply_text(
            f"🔥 *{escape_md(atk_name)}* casts **Crucio!**\n"
            f"💀 *{escape_md(dfn_name)}* has fallen!\n\n"
            f"🏆 *{escape_md(atk_name)} wins the duel!*",
            parse_mode="Markdown"
        )
        _end_duel(attacker, defender)
        return

    # Switch turn
    active_duel["turn"] = defender
    start_turn(defender)

    await update.message.reply_text(
        f"🔥 *{escape_md(atk_name)}* casts **Crucio!**\n"
        f"{escape_md(dfn_name)} ❤️{dfn['hp']}\n"
        f"{escape_md(atk_name)} ❤️{atk['hp']} ✨{atk['charisma']}\n\n"
        f"➡️ *{escape_md(dfn_name)}'s turn*",
        parse_mode="Markdown"
    )
async def debug_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Optional: restrict to admins only
    if user.id not in ADMINS:
        await update.message.reply_text("⛔ Admins only.")
        return

    # Reset / init player
    init_player(user.id)

    player_stats[user.id].update({
        "hp": 100,
        "charisma": 50,
        "shield": 0,
        "in_duel": True,
        "cooldowns": {}
    })

    # Start a self-duel
    active_duel.update({
        "active": True,
        "player1": user.id,
        "player2": user.id,
        "turn": user.id,
        "challenged": None,
    })

    # Start turn effects
    start_turn(user.id)

    await update.message.reply_text(
        "🧪 *Debug Duel Started*\n\n"
        "You are fighting yourself.\n"
        "Use `/cast_stupefy` to test spells.\n\n"
        "➡️ *Your turn*",
        parse_mode="Markdown"
    )

# ---------------- Quiz ----------------
SAMPLE_QUIZZES = [
    {
        "q": "What is the powerhouse of the cell?",
        "opts": ["Nucleus", "Mitochondria", "Ribosome", "Golgi"],
        "a": 2,
        "points": 5,
    },
    {
        "q": "Which vitamin is synthesised in skin on sunlight exposure?",
        "opts": ["Vitamin A", "Vitamin B12", "Vitamin C", "Vitamin D"],
        "a": 4,
        "points": 5,
    },
]


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = random.choice(SAMPLE_QUIZZES)
    text = f"*Quiz Time!* {escape_md(q['q'])}\n\n"
    for i, opt in enumerate(q["opts"], start=1):
        text += f"{i}. {escape_md(opt)}\n"
    # store correct answer in user_data
    context.user_data["quiz_answer"] = q["a"]
    context.user_data["quiz_points"] = q.get("points", 3)
    await update.message.reply_text(text + "\nReply with the option number (e.g. 1).", parse_mode="Markdown")


async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "quiz_answer" not in context.user_data:
        return  # ignore non-quiz messages
    try:
        ans = int(update.message.text.strip().split()[0])
    except Exception:
        await update.message.reply_text("Please reply with the option number (e.g. 1).")
        return
    correct = context.user_data.pop("quiz_answer", None)
    pts = context.user_data.pop("quiz_points", 3)
    uid = update.effective_user.id
    if ans == int(correct):
        quiz_scores[uid] = quiz_scores.get(uid, 0) + pts
        await save_data()
        await update.message.reply_text(f"✅ Correct! You earned {pts} points.")
    else:
        await update.message.reply_text("❌ Incorrect. Better luck next time.")


# ---------------- Admin & Moderation ----------------
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /addadmin <user_id> <display_name>
    # Only existing admin can add new admin
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only admins can add another admin.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addadmin <user_id> <display_name>")
        return
    try:
        new_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("user_id must be an integer.")
        return
    display = " ".join(context.args[1:])
    ADMIN_IDS[new_id] = display
    await save_data()
    await update.message.reply_text(f"✅ Added admin {escape_md(display)} ({new_id}).", parse_mode="Markdown")


async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only admins can remove admin.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        rem = int(context.args[0])
    except Exception:
        await update.message.reply_text("user_id must be integer.")
        return
    if rem in ADMIN_IDS:
        ADMIN_IDS.pop(rem, None)
        await save_data()
        await update.message.reply_text(f"✅ Removed admin {rem}.")
    else:
        await update.message.reply_text("That user is not an admin.")


# Unsor / Resort (admin)
async def unsort_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can unsort users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and use /unsort.")
        return

    target = update.message.reply_to_message.from_user

    if target.id not in user_houses:
        await update.message.reply_text("That user is not sorted.")
        return

    old_house = user_houses.pop(target.id)
    user_names.pop(target.id, None)

    await save_data()

    await update.message.reply_text(
        f"🪄 {escape_md(target.first_name)} removed from *{escape_md(old_house)}*.",
        parse_mode="Markdown"
    )


async def resort_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can resort users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and use /resort.")
        return

    target = update.message.reply_to_message.from_user
    new_house = random.choice(HOUSES)

    user_houses[target.id] = new_house
    user_names[target.id] = target.first_name

    await save_data()

    await update.message.reply_text(
        f"🔮 {escape_md(target.first_name)} has been sorted into *{escape_md(new_house)}*!",
        parse_mode="Markdown"
    )


# Moderation spells
async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can mute users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the user's message to mute them.")
        return

    target = update.message.reply_to_message.from_user

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(
            f"🔇 {escape_md(target.first_name)} has been muted.",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ Failed to mute (missing permissions?).")


async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can warn users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the user's message to warn them.")
        return

    target = update.message.reply_to_message.from_user

    await update.message.reply_text(
        f"⚠️ {escape_md(target.first_name)} has been warned.",
        parse_mode="Markdown"
    )


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can ban users.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the user's message to ban them.")
        return

    target = update.message.reply_to_message.from_user

    try:
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id
        )
        await update.message.reply_text(
            f"🚫 {escape_md(target.first_name)} has been banned.",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ Failed to ban (missing permissions?).")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your ID is: {update.effective_user.id}"
    )


# ----------------- STARTUP / MAIN -----------------
def main():
    # safety check
    if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN missing. Set BOT_TOKEN env var or hardcode temporarily (not recommended).")

    # Load persistent data synchronously
    load_data_sync()
    print("DEBUG: Data loaded - users:", len(user_houses))

    # Ensure an event loop exists for python-telegram-bot internals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Build application
    app = Application.builder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sortme", sortme))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("houseinfo", houseinfo))
    app.add_handler(CommandHandler("points", points))
    app.add_handler(CommandHandler("leaderboard", leaderboard))

    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_quiz_answer))

    # Admin / moderation handlers
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))

    app.add_handler(CommandHandler("unsort", unsort_user))
    app.add_handler(CommandHandler("resort", resort_user))

    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("deductpoints", deductpoints))

    app.add_handler(CommandHandler("expelliarmus", mute_user))
    app.add_handler(CommandHandler("stupefy", warn_user))
    app.add_handler(CommandHandler("avadakedavra", ban_user))

    app.add_handler(CommandHandler("duel", duel))
    app.add_handler(CommandHandler("accept", accept))
    app.add_handler(CommandHandler("decline", decline))
    app.add_handler(CommandHandler("cast_stupefy", cast_stupefy))
    app.add_handler(CommandHandler("cast_crucio", cast_crucio))
    app.add_handler(CommandHandler("debug_duel", debug_duel))
    app.add_handler(CommandHandler("myid", myid))
    # ensure process isn't killed by platforms expecting a web port
    _start_health_server()

    print("🏰 Hogwarts Bot is Now Online!")
    # This blocks and runs the bot. (No asyncio.run to avoid nested loop issues.)
    app.run_polling()


if __name__ == "__main__":
    main()