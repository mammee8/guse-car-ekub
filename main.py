import os
import sys
import logging
import psycopg2

try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        ConversationHandler,
        filters,
    )
except ImportError:
    print("❌ Missing dependencies. Ensure requirements.txt is installed.")
    sys.exit(1)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---------------------------------------------------------
# ENVIRONMENT VARIABLES & CONFIG
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip().isdigit()]
MAX_NUMBERS = 3500

WAITING_CHECK_NUM, WAITING_RESERVE_NUM = range(2)

# Button Text Constants
BTN_CHECK = "🔍 Check Number"
BTN_LIST = "📋 List Numbers"
BTN_RESERVE = "📌 Reserve Number"
BTN_RESERVED_LIST = "📑 Reserved List"
BTN_STATUS = "📊 Lotto Status"

# ---------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------
def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing!")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_num INT PRIMARY KEY,
            status TEXT NOT NULL,
            reserved_by BIGINT
        );
    """)
    cur.execute("SELECT COUNT(*) FROM tickets;")
    count = cur.fetchone()[0]
    
    if count == 0:
        logging.info("Seeding 3,500 tickets into PostgreSQL...")
        tickets = [(i, "available", None) for i in range(1, MAX_NUMBERS + 1)]
        cur.executemany("INSERT INTO tickets (ticket_num, status, reserved_by) VALUES (%s, %s, %s);", tickets)
    
    conn.commit()
    cur.close()
    conn.close()

def get_ticket(num: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticket_num, status, reserved_by FROM tickets WHERE ticket_num = %s;", (num,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return {"ticket_num": row[0], "status": row[1], "reserved_by": row[2]} if row else None

def reserve_ticket(num: int, user_id: int) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM tickets WHERE ticket_num = %s;", (num,))
    row = cur.fetchone()
    
    if not row or row[0] == "reserved":
        cur.close()
        conn.close()
        return False
        
    cur.execute("UPDATE tickets SET status = 'reserved', reserved_by = %s WHERE ticket_num = %s;", (user_id, num))
    conn.commit()
    cur.close()
    conn.close()
    return True

def get_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'reserved';")
    reserved = cur.fetchone()[0]
    cur.close()
    conn.close()
    return (MAX_NUMBERS - reserved, reserved)

def get_reserved_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ticket_num FROM tickets WHERE status = 'reserved' ORDER BY ticket_num ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]

# ---------------------------------------------------------
# CUSTOM KEYBOARD BUILDER
# ---------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def build_custom_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Builds a persistent bottom custom keyboard layout."""
    if is_admin(user_id):
        keyboard = [
            [KeyboardButton(BTN_CHECK), KeyboardButton(BTN_RESERVE)],
            [KeyboardButton(BTN_LIST), KeyboardButton(BTN_RESERVED_LIST)],
            [KeyboardButton(BTN_STATUS)]
        ]
    else:
        keyboard = [
            [KeyboardButton(BTN_CHECK), KeyboardButton(BTN_LIST)]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------------------------------------------------
# HANDLERS
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    role = "👑 Admin" if is_admin(user.id) else "👤 User"
    
    await update.message.reply_text(
        f"Welcome to Car Lottery Bot!\nRole: {role}\n\nUse the custom keyboard below to navigate:",
        reply_markup=build_custom_keyboard(user.id)
    )
    return ConversationHandler.END

async def menu_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text

    # Route: Check Number
    if text == BTN_CHECK:
        await update.message.reply_text(
            f"Please enter the ticket number you want to check (1 - {MAX_NUMBERS}):",
            reply_markup=build_custom_keyboard(user_id)
        )
        return WAITING_CHECK_NUM

    # Route: Reserve Number (Admin Only)
    elif text == BTN_RESERVE:
        if not is_admin(user_id):
            await update.message.reply_text("⛔ **Access Denied**: Admins only.", reply_markup=build_custom_keyboard(user_id), parse_mode="Markdown")
            return ConversationHandler.END
            
        await update.message.reply_text(
            f"Please enter the ticket number you want to reserve (1 - {MAX_NUMBERS}):",
            reply_markup=build_custom_keyboard(user_id)
        )
        return WAITING_RESERVE_NUM

    # Route: List Numbers
    elif text == BTN_LIST:
        avail, res = get_stats()
        await update.message.reply_text(
            f"📋 **Lotto Numbers Overview**\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {avail}\n"
            f"• Reserved: {res}",
            reply_markup=build_custom_keyboard(user_id),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Route: Reserved List (Admin Only)
    elif text == BTN_RESERVED_LIST:
        if not is_admin(user_id):
            await update.message.reply_text("⛔ **Access Denied**: Admins only.", reply_markup=build_custom_keyboard(user_id), parse_mode="Markdown")
            return ConversationHandler.END

        res_list = get_reserved_list()
        if not res_list:
            msg = "📑 **Reserved List**: No numbers reserved yet."
        else:
            msg = f"📑 **Reserved Numbers ({len(res_list)} total):**\n" + ", ".join(map(str, res_list[:50]))
            
        await update.message.reply_text(msg, reply_markup=build_custom_keyboard(user_id), parse_mode="Markdown")
        return ConversationHandler.END

    # Route: Lotto Status (Admin Only)
    elif text == BTN_STATUS:
        if not is_admin(user_id):
            await update.message.reply_text("⛔ **Access Denied**: Admins only.", reply_markup=build_custom_keyboard(user_id), parse_mode="Markdown")
            return ConversationHandler.END

        avail, res = get_stats()
        pct = (res / MAX_NUMBERS) * 100
        await update.message.reply_text(
            f"📊 **Car Lottery Dashboard**\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {avail}\n"
            f"• Reserved: {res}\n"
            f"• Sales Progress: {pct:.1f}%",
            reply_markup=build_custom_keyboard(user_id),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    return ConversationHandler.END

async def process_check_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text in [BTN_CHECK, BTN_LIST, BTN_RESERVE, BTN_RESERVED_LIST, BTN_STATUS]:
        return await menu_navigation(update, context)

    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Enter a valid number between 1 and {MAX_NUMBERS}:",
            reply_markup=build_custom_keyboard(user_id)
        )
        return WAITING_CHECK_NUM

    num = int(text)
    record = get_ticket(num)
    status_msg = f"🟢 Ticket #{num} is AVAILABLE!" if record and record["status"] == "available" else f"🔴 Ticket #{num} is RESERVED."
    
    await update.message.reply_text(status_msg, reply_markup=build_custom_keyboard(user_id))
    return ConversationHandler.END

async def process_reserve_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text in [BTN_CHECK, BTN_LIST, BTN_RESERVE, BTN_RESERVED_LIST, BTN_STATUS]:
        return await menu_navigation(update, context)

    if not is_admin(user_id):
        await update.message.reply_text("⛔ Admin action required.", reply_markup=build_custom_keyboard(user_id))
        return ConversationHandler.END

    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Enter a valid number between 1 and {MAX_NUMBERS}:",
            reply_markup=build_custom_keyboard(user_id)
        )
        return WAITING_RESERVE_NUM

    num = int(text)
    if reserve_ticket(num, user_id):
        await update.message.reply_text(
            f"✅ Ticket #{num} successfully reserved in PostgreSQL!",
            reply_markup=build_custom_keyboard(user_id)
        )
    else:
        await update.message.reply_text(
            f"⚠️ Ticket #{num} is already reserved!",
            reply_markup=build_custom_keyboard(user_id)
        )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.", reply_markup=build_custom_keyboard(update.effective_user.id))
    return ConversationHandler.END

# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------
def main():
    if not BOT_TOKEN or not DATABASE_URL:
        print("❌ Error: BOT_TOKEN and DATABASE_URL environment variables must be set.")
        sys.exit(1)
        
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, menu_navigation)
        ],
        states={
            WAITING_CHECK_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_check_number)],
            WAITING_RESERVE_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_reserve_number)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🚀 Custom Keyboard Bot running with PostgreSQL persistence...")
    app.run_polling()

if __name__ == "__main__":
    main()
