"""
=============================================================================
CAR LOTTERY TELEGRAM BOT WITH RENDER POSTGRESQL PERSISTENCE
=============================================================================
Dependencies required in requirements.txt:
    python-telegram-bot>=20.0
    psycopg2-binary>=2.9.0
=============================================================================
"""

import os
import sys
import logging
import psycopg2

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        ContextTypes,
        ConversationHandler,
        filters,
    )
except ImportError:
    print("❌ Error: Dependencies missing. Ensure requirements.txt is configured properly.")
    sys.exit(1)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Add numeric Telegram User ID(s) here or via ENV
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "123456789").split(",") if i.isdigit()]
MAX_NUMBERS = 3500

# Conversation States
WAITING_CHECK_NUM, WAITING_RESERVE_NUM = range(2)


# ---------------------------------------------------------
# DATABASE PERSISTENCE HELPERS (PostgreSQL)
# ---------------------------------------------------------
def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing!")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Creates table and seeds initial 3500 tickets if they do not exist."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Create table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_num INT PRIMARY KEY,
            status TEXT NOT NULL,
            reserved_by BIGINT
        );
    """)

    # Seed 3500 tickets if empty
    cur.execute("SELECT COUNT(*) FROM tickets;")
    count = cur.fetchone()[0]

    if count == 0:
        logging.info("Initializing database with 3,500 lottery tickets...")
        tickets_data = [(i, "available", None) for i in range(1, MAX_NUMBERS + 1)]
        cur.executemany(
            "INSERT INTO tickets (ticket_num, status, reserved_by) VALUES (%s, %s, %s);",
            tickets_data,
        )

    conn.commit()
    cur.close()
    conn.close()


def get_ticket(num: int):
    """Retrieve ticket details from Database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticket_num, status, reserved_by FROM tickets WHERE ticket_num = %s;", (num,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {"ticket_num": row[0], "status": row[1], "reserved_by": row[2]}
    return None


def reserve_ticket(num: int, user_id: int) -> bool:
    """Reserve a ticket inside Database permanently."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Double check state
    cur.execute("SELECT status FROM tickets WHERE ticket_num = %s;", (num,))
    row = cur.fetchone()

    if not row or row[0] == "reserved":
        cur.close()
        conn.close()
        return False

    cur.execute(
        "UPDATE tickets SET status = 'reserved', reserved_by = %s WHERE ticket_num = %s;",
        (user_id, num),
    )
    conn.commit()
    cur.close()
    conn.close()
    return True


def get_stats():
    """Retrieve overview metrics from Database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'reserved';")
    reserved_count = cur.fetchone()[0]
    cur.close()
    conn.close()

    available_count = MAX_NUMBERS - reserved_count
    return available_count, reserved_count


def get_reserved_list():
    """Retrieve list of all reserved ticket numbers."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticket_num FROM tickets WHERE status = 'reserved' ORDER BY ticket_num ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------
# BOT HELPER FUNCTIONS
# ---------------------------------------------------------
def is_admin(user_id: int) -> bool:
    """Check if requesting user ID is an admin."""
    return user_id in ADMIN_IDS


def build_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build dynamic keyboard layout based on user role."""
    if is_admin(user_id):
        keyboard = [
            [
                InlineKeyboardButton("🔍 Check Number", callback_data="btn_check"),
                InlineKeyboardButton("📌 Reserve Number", callback_data="btn_reserve"),
            ],
            [
                InlineKeyboardButton("📋 List Numbers", callback_data="btn_list"),
                InlineKeyboardButton("📑 Reserved List", callback_data="btn_reserved_list"),
            ],
            [
                InlineKeyboardButton("📊 Lotto Status", callback_data="btn_status"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("🔍 Check Number", callback_data="btn_check"),
                InlineKeyboardButton("📋 List Numbers", callback_data="btn_list"),
            ]
        ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------
# TELEGRAM HANDLERS
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles /start command."""
    user = update.effective_user
    role_text = "👑 **Admin**" if is_admin(user.id) else "👤 **User**"

    await update.message.reply_text(
        f"Welcome to the Car Lottery Bot!\nRole: {role_text}\n\nSelect an option below:",
        reply_markup=build_menu_keyboard(user.id),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes button callbacks."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action = query.data

    admin_only_actions = ["btn_reserve", "btn_reserved_list", "btn_status"]
    if action in admin_only_actions and not is_admin(user_id):
        await query.edit_message_text(
            "⛔ **Access Denied**: You do not have permission to use this feature.",
            reply_markup=build_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    if action == "btn_check":
        await query.edit_message_text(f"Please enter the ticket number to check (1 - {MAX_NUMBERS}):")
        return WAITING_CHECK_NUM

    elif action == "btn_reserve":
        await query.edit_message_text(f"Please enter the ticket number to reserve (1 - {MAX_NUMBERS}):")
        return WAITING_RESERVE_NUM

    elif action == "btn_list":
        available_count, reserved_count = get_stats()
        await query.edit_message_text(
            f"📋 **Lotto Numbers Overview**\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {available_count}\n"
            f"• Reserved: {reserved_count}\n\n"
            f"*(Use 'Check Number' to query a specific ticket)*",
            reply_markup=build_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    elif action == "btn_reserved_list":
        reserved_items = get_reserved_list()
        if not reserved_items:
            text = "📑 **Reserved List**: No numbers have been reserved yet."
        else:
            sample = reserved_items[:50]
            text = f"📑 **Reserved Numbers ({len(reserved_items)} total):**\n" + ", ".join(map(str, sample))
            if len(reserved_items) > 50:
                text += "\n\n*(Displaying first 50 items to fit Telegram payload limits)*"

        await query.edit_message_text(text, reply_markup=build_menu_keyboard(user_id))
        return ConversationHandler.END

    elif action == "btn_status":
        available_count, reserved_count = get_stats()
        percent_filled = (reserved_count / MAX_NUMBERS) * 100

        await query.edit_message_text(
            f"📊 **Car Lottery Dashboard**\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {available_count}\n"
            f"• Reserved: {reserved_count}\n"
            f"• Sales Progress: {percent_filled:.1f}%",
            reply_markup=build_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return ConversationHandler.END


async def process_check_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes user input for ticket lookup."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Invalid input. Enter a valid integer between 1 and {MAX_NUMBERS}:"
        )
        return WAITING_CHECK_NUM

    num = int(text)
    record = get_ticket(num)

    if record and record["status"] == "available":
        status_msg = f"🟢 **Ticket #{num} is AVAILABLE!**"
    else:
        status_msg = f"🔴 **Ticket #{num} is RESERVED.**"

    await update.message.reply_text(
        status_msg,
        reply_markup=build_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def process_reserve_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes admin input for reserving ticket."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Permission error.", reply_markup=build_menu_keyboard(user_id)
        )
        return ConversationHandler.END

    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Invalid input. Enter a valid integer between 1 and {MAX_NUMBERS}:"
        )
        return WAITING_RESERVE_NUM

    num = int(text)
    success = reserve_ticket(num, user_id)

    if not success:
        await update.message.reply_text(
            f"⚠️ Ticket #{num} is already reserved!",
            reply_markup=build_menu_keyboard(user_id),
        )
    else:
        await update.message.reply_text(
            f"✅ **Success!** Ticket #{num} has been marked as reserved in PostgreSQL.",
            reply_markup=build_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels active conversations."""
    await update.message.reply_text(
        "Operation cancelled.", reply_markup=build_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END


# ---------------------------------------------------------
# APPLICATION ENTRYPOINT
# ---------------------------------------------------------
def main():
    # Initialize Database Tables
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_CHECK_NUM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_check_number)
            ],
            WAITING_RESERVE_NUM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_reserve_number)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🚀 Bot is live with PostgreSQL Persistence...")
    app.run_polling()


if __name__ == "__main__":
    main()
