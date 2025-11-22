import asyncio
import random

from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================

# No env var, direct token
TOKEN = "8214478922:AAEeLgZD3aUSKeN_voD-Aw7Eymd3Ow4bCHU"



HOUSES = ["Gryffindor", "Ravenclaw", "Hufflepuff", "Slytherin"]

# user_id -> house
user_houses = {}

# house -> points
house_points = {h: 0 for h in HOUSES}

# Put your Telegram user ID here (get using @userinfobot)
ADMIN_IDS = {
    8021336166: "Professor Shadow",  # Replace with your ID
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ================== BASIC COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🏰 Welcome to Hogwarts, {user.first_name}!\n"
        "Use /sortme to get your house.\n"
        "Use /points to see house standings.\n"
        "Use /quiz for a NEET-style question 🧠"
    )


async def sortme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_houses:
        house = user_houses[user.id]
    else:
        house = random.choice(HOUSES)
        user_houses[user.id] = house

    spark = random.choice(["✨", "⚡", "🪄", "🌟"])
    await update.message.reply_text(
        f"🎩 The Sorting Hat has spoken!\n"
        f"You’ve been sorted into *{house}* {spark}",
        parse_mode="Markdown",
    )

# ================== ADMIN SORTING HAT ==================

async def hatsort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user

    # Only admins can use this
    if not is_admin(admin.id):
        await update.message.reply_text("🚫 Only professors can use the Sorting Hat manually.")
        return

    # Must be used as a reply
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a student's message and use:\n`/hatsort <optional_house>`", parse_mode="Markdown")
        return

    target = update.message.reply_to_message.from_user

    # If admin gave a house, use it. Otherwise assign random.
    if context.args:
        house = context.args[0].capitalize()
        if house not in HOUSES:
            await update.message.reply_text(
                "❌ Invalid house name.\nUse one of: Gryffindor, Slytherin, Ravenclaw, Hufflepuff."
            )
            return
    else:
        house = random.choice(HOUSES)

    # Save in the same dict used by /sortme
    user_houses[target.id] = house

    target_name = "@" + target.username if target.username else target.first_name
    spark = random.choice(["✨", "⚡", "🪄", "🌟"])
    await update.message.reply_text(
        f"🎩 The Sorting Hat has *manually* spoken!\n"
        f"{target_name} has been placed in *{house}* {spark}",
        parse_mode="Markdown",
    )

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🏆 *Current House Points:*\n\n"
    for house in HOUSES:
        pts = house_points.get(house, 0)
        spark = random.choice(["✨", "⚡", "🪄", "🌟"])
        msg += f"{spark} {house}: {pts} points\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


# ================== QUIZ SYSTEM ==================

QUIZ_QUESTIONS = [
    {
        "question": "Which blood group is universal donor?",
        "options": ["A", "B", "AB", "O"],
        "answer_index": 3,
        "points": 10,
    },
    {
        "question": "Deficiency of which vitamin causes scurvy?",
        "options": ["A", "B12", "C", "D"],
        "answer_index": 2,
        "points": 10,
    },
]

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = random.choice(QUIZ_QUESTIONS)
    context.chat_data["current_quiz"] = q

    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])

    await update.message.reply_text(
        f"❓ *NEET Quiz Time!*\n\n"
        f"{q['question']}\n\n"
        f"{options_text}\n\n"
        f"Reply with the option number (1-{len(q['options'])})",
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
    except ValueError:
        await update.message.reply_text("⚠️ Reply with the *number* of the option.", parse_mode="Markdown")
        return

    if chosen == q["answer_index"]:
        if user.id not in user_houses:
            await update.message.reply_text("You’re not sorted yet! Use /sortme first 🧙‍♂️")
            return

        house = user_houses[user.id]
        house_points[house] += q["points"]

        await update.message.reply_text(
            f"✨ Correct! {q['points']} points to *{house}*! ⚡",
            parse_mode="Markdown",
        )
    else:
        correct_opt = q["options"][q["answer_index"]]
        await update.message.reply_text(
            f"❌ Incorrect.\nRight answer: *{correct_opt}*.",
            parse_mode="Markdown",
        )

    context.chat_data.pop("current_quiz", None)

# ================== ADMIN POINT COMMANDS ==================

async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
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
    except ValueError:
        await update.message.reply_text("⚠️ Points must be a number.")
        return

    house_points[house] += pts
    await update.message.reply_text(f"✨ Added {pts} points to *{house}*!", parse_mode="Markdown")

async def deductpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
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
    except ValueError:
        await update.message.reply_text("⚠️ Points must be a number.")
        return

    house_points[house] -= pts
    await update.message.reply_text(f"⚠️ Deducted {pts} points from *{house}*.", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_houses = sorted(house_points.items(), key=lambda x: x[1], reverse=True)

    msg = "🏆 *House Leaderboard:*\n\n"
    for i, (house, pts) in enumerate(sorted_houses, start=1):
        symbol = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else "⭐"
        msg += f"{symbol} {house}: {pts} points\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ================== SPELLS ==================

async def expelliarmus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only professors can cast *Expelliarmus*.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to someone’s message to mute them.")
        return

    target = update.message.reply_to_message.from_user
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        target.id,
        permissions=ChatPermissions(can_send_messages=False),
    )
    await update.message.reply_text(f"🪄 *Expelliarmus!* {target.first_name} is muted!")


async def avadakedavra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only professors can cast the Killing Curse.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to someone’s message to ban them.")
        return

    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"💀 *Avada Kedavra!* {target.first_name} is gone!")


async def stupefy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only professors can stun students.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to someone’s message to warn them.")
        return

    target = update.message.reply_to_message.from_user
    await update.message.reply_text(f"⚡ *Stupefy!* {target.first_name} has been warned!")


# ================== MAIN ==================

def main():
    

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sortme", sortme))
    app.add_handler(CommandHandler("hatsort", hatsort))
    app.add_handler(CommandHandler("points", points))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("deductpoints", deductpoints))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("expelliarmus", expelliarmus))
    app.add_handler(CommandHandler("avadakedavra", avadakedavra))
    app.add_handler(CommandHandler("stupefy", stupefy))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))

    print("🏰 Hogwarts Bot is Now Online!")
    app.run_polling()  # 🔹 No await here


if __name__ == "__main__":
    main()  # 🔹 No asyncio.run()
