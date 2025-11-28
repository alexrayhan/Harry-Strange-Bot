# bot.py - Hogwarts NEET GC Bot (full, persistent version)
# Works with python-telegram-bot==21.4
# Persistence: data.json (automatic). Make sure the file is writable in the container.

import os
import json
import random
import asyncio
from typing import Dict, Any

from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- CONFIG -----------------
# TOKEN is read from environment variable BOT_TOKEN by default.
# For quick local testing, you may replace the fallback string with your token (NOT recommended for public repos).
TOKEN = "8214478922:AAEeLgZD3aUSKeN_voD-Aw7Eymd3Ow4bCHU" or "PASTE_YOUR_TOKEN_HERE"

# ----------------- PERSISTENCE ENGINE -----------------
DATA_FILE = "data.json"
data_lock = asyncio.Lock()

HOUSES = ["Gryffindor", "Ravenclaw", "Hufflepuff", "Slytherin"]

# runtime data structures (populated by load_data)
user_houses: Dict[int, str] = {}     # user_id -> house
user_names: Dict[int, str] = {}      # user_id -> display name
house_points: Dict[str, int] = {h: 0 for h in HOUSES}  # house -> points
ADMIN_IDS: Dict[int, str] = {}       # user_id -> display name
quiz_scores: Dict[int, int] = {}     # user_id -> total quiz points
duel_wins: Dict[int, int] = {}       # user_id -> wins

def _default_data() -> Dict[str, Any]:
    return {
        "user_houses": {},
        "user_names": {},
        "house_points": {h: 0 for h in HOUSES},
        "ADMIN_IDS": {},
        "quiz_scores": {},
        "duel_wins": {},
    }

def _sync_write(data: Dict[str, Any]):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def _sync_read() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return _default_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return _default_data()

async def save_data():
    """Save runtime data to data.json in a background thread."""
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

# Synchronous loader (safe at startup — doesn't create/close an asyncio loop)
def load_data_sync():
    loaded = _sync_read()

    # user_houses
    uh = {}
    for k, v in loaded.get("user_houses", {}).items():
        try:
            uh[int(k)] = v
        except Exception:
            pass
    user_houses.clear()
    user_houses.update(uh)

    # user_names
    un = {}
    for k, v in loaded.get("user_names", {}).items():
        try:
            un[int(k)] = v
        except Exception:
            pass
    user_names.clear()
    user_names.update(un)

    # house_points (ensure houses exist)
    hp = loaded.get("house_points", {})
    for h in HOUSES:
        house_points[h] = int(hp.get(h, 0))

    # ADMIN_IDS
    adm = {}
    for k, v in loaded.get("ADMIN_IDS", {}).items():
        try:
            adm[int(k)] = v
        except Exception:
            pass
    ADMIN_IDS.clear()
    ADMIN_IDS.update(adm)

    # quiz_scores
    qs = {}
    for k, v in loaded.get("quiz_scores", {}).items():
        try:
            qs[int(k)] = int(v)
        except Exception:
            pass
    quiz_scores.clear()
    quiz_scores.update(qs)

    # duel_wins
    dw = {}
    for k, v in loaded.get("duel_wins", {}).items():
        try:
            dw[int(k)] = int(v)
        except Exception:
            pass
    duel_wins.clear()
    duel_wins.update(dw)

def set_user_name_from_obj(user):
    """Store a display name for user (username if available else first name)."""
    if not user:
        return
    user_names[user.id] = "@" + user.username if user.username else (user.first_name or str(user.id))

# ----------------- HELPERS -----------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ----------------- BASIC COMMANDS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    set_user_name_from_obj(user)
    await update.message.reply_text(
        "🏰 Welcome to the Hogwarts Study Bot!\n\n"
        "Useful commands:\n"
        "/sortme — get sorted into a house\n"
        "/houseinfo — list houses and members\n"
        "/points — show house points\n"
        "/quiz — start a NEET quiz question\n\n"
        "Admins: /hatsort, /resort, /unsort, /addpoints, /deductpoints, /addadmin, /removeadmin"
    )

# ----------------- SORTING & ADMIN SORTS -----------------
async def sortme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_houses:
        house = user_houses[user.id]
    else:
        house = random.choice(HOUSES)
        user_houses[user.id] = house

    set_user_name_from_obj(user)
    await save_data()

    spark = random.choice(["✨", "⚡", "🪄", "🌟"])
    await update.message.reply_text(
        f"🎩 The Sorting Hat has spoken!\nYou’ve been sorted into *{house}* {spark}",
        parse_mode="Markdown",
    )

async def hatsort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can use this.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a student's message and use /hatsort <optional_house>")
        return

    target = update.message.reply_to_message.from_user
    if context.args:
        house = context.args[0].capitalize()
        if house not in HOUSES:
            await update.message.reply_text("❌ Invalid house name.")
            return
    else:
        house = random.choice(HOUSES)

    user_houses[target.id] = house
    user_names[target.id] = "@" + target.username if target.username else (target.first_name or str(target.id))
    await save_data()

    target_name = user_names[target.id]
    spark = random.choice(["✨", "⚡", "🪄", "🌟"])
    await update.message.reply_text(
        f"🎩 The Sorting Hat has *manually* spoken!\n{target_name} has been placed in *{house}* {spark}",
        parse_mode="Markdown",
    )

async def resort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can re-sort students.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a student's message and use /resort <house>")
        return

    if not context.args:
        await update.message.reply_text("You must specify a house. Example: /resort Gryffindor")
        return

    new_house = context.args[0].capitalize()
    if new_house not in HOUSES:
        await update.message.reply_text("❌ Invalid house name.")
        return

    target = update.message.reply_to_message.from_user
    user_houses[target.id] = new_house
    user_names[target.id] = "@" + target.username if target.username else (target.first_name or str(target.id))
    await save_data()

    target_name = user_names[target.id]
    spark = random.choice(["✨", "⚡", "🪄", "🌟"])
    await update.message.reply_text(
        f"🎩 The Sorting Hat has *changed its mind!*\n{target_name} has been moved to *{new_house}* {spark}",
        parse_mode="Markdown",
    )

async def unsort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can unsort students.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a student's message and use /unsort")
        return

    target = update.message.reply_to_message.from_user
    if target.id in user_houses:
        old_house = user_houses.pop(target.id)
        user_names.pop(target.id, None)
        await save_data()
        target_name = "@" + target.username if target.username else (target.first_name or str(target.id))
        await update.message.reply_text(
            f"🧹 {target_name} has been *removed* from *{old_house}*.\nThey can now use /sortme to be sorted again.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("🤔 That student is not sorted into any house yet.")

# ----------------- HOUSE INFO & POINTS -----------------
async def houseinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_houses:
        await update.message.reply_text("No one has been sorted into any house yet 🥲")
        return

    house_members = {house: [] for house in HOUSES}
    for user_id, house in user_houses.items():
        name = user_names.get(user_id, f"User {user_id}")
        house_members[house].append(name)

    house_emojis = {
        "Gryffindor": "🦁",
        "Slytherin": "🐍",
        "Ravenclaw": "🦅",
        "Hufflepuff": "🦡",
    }

    msg = "🏰 *Hogwarts House Information*\n\n"
    for house in HOUSES:
        emoji = house_emojis.get(house, "✨")
        members = house_members[house]
        count = len(members)
        if count == 0:
            msg += f"{emoji} *{house}*: No students yet\n\n"
        else:
            msg += f"{emoji} *{house}* — {count} students:\n"
            for m in members:
                msg += f" • {m}\n"
            msg += "\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🏆 *Current House Points:*\n\n"
    for h in HOUSES:
        msg += f"{h}: {house_points.get(h, 0)} points\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only professors can add points.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addpoints <house> <points>")
        return

    house = context.args[0].capitalize()
    if house not in HOUSES:
        await update.message.reply_text("❌ Invalid house name.")
        return

    try:
        pts = int(context.args[1])
    except Exception:
        await update.message.reply_text("⚠️ Points must be a number.")
        return

    house_points[house] = house_points.get(house, 0) + pts
    await save_data()
    await update.message.reply_text(f"✨ Added {pts} points to *{house}*.", parse_mode="Markdown")

async def deductpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only professors can deduct points.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /deductpoints <house> <points>")
        return

    house = context.args[0].capitalize()
    if house not in HOUSES:
        await update.message.reply_text("❌ Invalid house name.")
        return

    try:
        pts = int(context.args[1])
    except Exception:
        await update.message.reply_text("⚠️ Points must be a number.")
        return

    house_points[house] = house_points.get(house, 0) - pts
    await save_data()
    await update.message.reply_text(f"⚠️ Deducted {pts} points from *{house}*.", parse_mode="Markdown")

# ----------------- SIMPLE QUIZ SYSTEM -----------------
# small curated NEET-style questions; extend as needed
QUIZ_QUESTIONS = [
    {
        "question": "Which blood group is considered the universal donor?",
        "options": ["A", "B", "AB", "O"],
        "answer_index": 3,
        "points": 10,
    },
    {
        "question": "Deficiency of which vitamin causes scurvy?",
        "options": ["Vitamin A", "Vitamin B12", "Vitamin C", "Vitamin D"],
        "answer_index": 2,
        "points": 10,
    },
    {
        "question": "Which organelle is known as the powerhouse of the cell?",
        "options": ["Ribosome", "Mitochondria", "Golgi apparatus", "Nucleus"],
        "answer_index": 1,
        "points": 10,
    },
]

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = random.choice(QUIZ_QUESTIONS)
    context.chat_data["current_quiz"] = q
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    await update.message.reply_text(
        f"❓ *NEET Quiz Time!*\n\n{q['question']}\n\n{options_text}\n\nReply with the option number (1-{len(q['options'])})",
        parse_mode="Markdown",
    )

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "current_quiz" not in context.chat_data:
        return
    user = update.effective_user
    text = update.message.text.strip()
    q = context.chat_data["current_quiz"]

    try:
        chosen = int(text) - 1
    except Exception:
        await update.message.reply_text("⚠️ Reply with the *number* of the option.", parse_mode="Markdown")
        return

    if chosen < 0 or chosen >= len(q["options"]):
        await update.message.reply_text("⚠️ That option number is out of range.")
        return

    # ensure user sorted
    if user.id not in user_houses:
        await update.message.reply_text("You’re not sorted yet! Use /sortme first 🧙‍♂️")
        context.chat_data.pop("current_quiz", None)
        return

    house = user_houses[user.id]
    if chosen == q["answer_index"]:
        # correct
        house_points[house] = house_points.get(house, 0) + q["points"]
        quiz_scores[user.id] = quiz_scores.get(user.id, 0) + q["points"]
        await save_data()
        fireworks = " ".join(random.choices(["🎆", "🎇", "✨", "🌟"], k=3))
        await update.message.reply_text(f"✅ Correct! {q['points']} points to *{house}*! {fireworks}", parse_mode="Markdown")
    else:
        correct_opt = q["options"][q["answer_index"]]
        await update.message.reply_text(f"❌ Incorrect.\nRight answer: *{correct_opt}*.", parse_mode="Markdown")

    context.chat_data.pop("current_quiz", None)

# ----------------- SPELLS / MODERATION -----------------
async def expelliarmus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can cast Expelliarmus.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and use /expelliarmus to mute them.")
        return

    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        await update.message.reply_text(f"🪄 {ADMIN_IDS.get(admin.id,'Professor')} cast *Expelliarmus!* {user_names.get(target.id, target.first_name)} has been muted.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Spell failed — I might not be admin or lack permissions.")

async def avadakedavra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can cast Avada Kedavra.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and use /avadakedavra to ban them.")
        return

    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=target.id)
        await update.message.reply_text(f"💀 {ADMIN_IDS.get(admin.id,'Professor')} whispered *Avada Kedavra!* {user_names.get(target.id, target.first_name)} has been banned.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("The curse failed — I might not have ban permissions.")

async def stupefy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can cast Stupefy.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and use /stupefy to warn them.")
        return

    target = update.message.reply_to_message.from_user
    await update.message.reply_text(f"✨ {ADMIN_IDS.get(admin.id,'Professor')} cast *Stupefy!* {user_names.get(target.id, target.first_name)} has been warned.", parse_mode="Markdown")

# ----------------- ADMIN MANAGEMENT -----------------
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only an existing professor can add admins.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /addadmin <user_id> <display_name_optional>")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid user id.")
        return
    name = " ".join(context.args[1:]) if len(context.args) > 1 else "Professor"
    ADMIN_IDS[uid] = name
    await save_data()
    await update.message.reply_text(f"✅ Added admin: {name} ({uid})")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin(caller.id):
        await update.message.reply_text("🚫 Only an existing professor can remove admins.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid user id.")
        return
    removed = ADMIN_IDS.pop(uid, None)
    await save_data()
    await update.message.reply_text(f"✅ Removed admin: {removed if removed else uid}")

# ----------------- UTILITY COMMANDS -----------------
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user_names.get(user.id, "Unknown")
    house = user_houses.get(user.id, None)
    msg = f"🪄 {name}\n"
    if house:
        msg += f"House: *{house}*\n"
    else:
        msg += "You are not yet sorted. Use /sortme.\n"
    msg += f"Total quiz points: {quiz_scores.get(user.id, 0)}\nWins (duels): {duel_wins.get(user.id, 0)}"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ----------------- STARTUP & MAIN -----------------
print("DEBUG: TOKEN present:", bool(TOKEN))
print("DEBUG: Data loaded, users:", len(user_houses))
import asyncio as _a
print("DEBUG: current event loop:", _a.get_event_loop())

def main():
    # token safety check (keep or replace with hardcode if you did)
    if TOKEN.startswith("PASTE_") or not TOKEN:
        raise RuntimeError("Please set your bot token in the BOT_TOKEN environment variable or replace the fallback in code.")

    # ---- load data synchronously (no event loop created/closed) ----
    load_data_sync()

    # ---- ensure a running event loop exists for python-telegram-bot internals ----
    # Create & set a fresh event loop for the main thread (prevents "no current event loop" errors)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Build and run the bot (app.run_polling will use the loop we just set)
    app = ApplicationBuilder().token(TOKEN).build()

    # (re)register handlers here (your existing app.add_handler(...) lines)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))

    app.add_handler(CommandHandler("sortme", sortme))
    app.add_handler(CommandHandler("hatsort", hatsort))
    app.add_handler(CommandHandler("resort", resort))
    app.add_handler(CommandHandler("unsort", unsort))
    app.add_handler(CommandHandler("houseinfo", houseinfo))

    app.add_handler(CommandHandler("points", points))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("deductpoints", deductpoints))

    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_quiz_answer))

    app.add_handler(CommandHandler("expelliarmus", expelliarmus))
    app.add_handler(CommandHandler("stupefy", stupefy))
    app.add_handler(CommandHandler("avadakedavra", avadakedavra))

    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))

    print("🏰 Hogwarts Bot is Now Online!")
    app.run_polling()