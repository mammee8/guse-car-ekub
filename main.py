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
# TABBED NAVIGATION KEYBOARD BUILDER
# ---------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def build_tabbed_keyboard(user_id: int, active_tab: str) -> InlineKeyboardMarkup:
    """Builds a tabbed navigation bar highlighting the active tab."""
    
    # Define Tab Headers with visual indicator for active tab
    check_label = "🔘 Check" if active_tab == "check" else "🔍 Check"
    list_label = "🔘 List" if active_tab == "list" else "📋 List"
    reserve_label = "🔘 Reserve" if active_tab == "reserve" else "📌 Reserve"
    res_list_label = "🔘 Reserved List" if active_tab == "reserved_list" else "📑 Reserved List"
    status_label = "🔘 Status" if active_tab == "status" else "📊 Status"

    if is_admin(user_id):
        # Admin gets full tab bar layout
        keyboard = [
            # Tab Bar Row 1
            [
                InlineKeyboardButton(check_label, callback_data="tab_check"),
                InlineKeyboardButton(reserve_label, callback_data="tab_reserve"),
            ],
            # Tab Bar Row 2
            [
                InlineKeyboardButton(list_label, callback_data="tab_list"),
                InlineKeyboardButton(res_list_label, callback_data="tab_reserved_list"),
            ],
            # Tab Bar Row 3
            [
                InlineKeyboardButton(status_label, callback_data="tab_status"),
            ]
        ]
    else:
        # Regular users get public tabs only
        keyboard = [
            [
                InlineKeyboardButton(check_label, callback_data="tab_check"),
                InlineKeyboardButton(list_label, callback_data="tab_list"),
            ]
        ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# HANDLERS
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    role = "👑 Admin" if is_admin(user.id) else "👤 User"
    
    await update.message.reply_text(
        f" Welcome to Car Lottery Bot!\nRole: {role}\n\nSelect a tab below to switch views:",
        reply_markup=build_tabbed_keyboard(user.id, active_tab="check")
    )
    return ConversationHandler.END

async def tab_switch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data

    # Security check for admin tabs
    admin_tabs = ["tab_reserve", "tab_reserved_list", "tab_status"]
    if action in admin_tabs and not is_admin(user_id):
        await query.edit_message_text(
            "⛔ **Access Denied**: Admins only.",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="check"),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Tab 1: Check Number
    if action == "tab_check":
        await query.edit_message_text(
            f"--- 📌 **TAB: CHECK NUMBER** ---\n\n"
            f"Please reply with the ticket number you want to check (1 - {MAX_NUMBERS}):",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="check"),
            parse_mode="Markdown"
        )
        return WAITING_CHECK_NUM

    # Tab 2: Reserve Number (Admin)
    elif action == "tab_reserve":
        await query.edit_message_text(
            f"--- 📌 **TAB: RESERVE NUMBER** ---\n\n"
            f"Please reply with the ticket number you want to reserve (1 - {MAX_NUMBERS}):",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="reserve"),
            parse_mode="Markdown"
        )
        return WAITING_RESERVE_NUM

    # Tab 3: List Overview
    elif action == "tab_list":
        avail, res = get_stats()
        await query.edit_message_text(
            f"--- 📋 **TAB: TICKETS OVERVIEW** ---\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {avail}\n"
            f"• Reserved: {res}",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="list"),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Tab 4: Reserved List (Admin)
    elif action == "tab_reserved_list":
        res_list = get_reserved_list()
        if not res_list:
            text = "--- 📑 **TAB: RESERVED LIST** ---\n\nNo numbers reserved yet."
        else:
            text = (
                f"--- 📑 **TAB: RESERVED LIST ({len(res_list)} total)** ---\n\n"
                + ", ".join(map(str, res_list[:50]))
            )
        await query.edit_message_text(
            text,
            reply_markup=build_tabbed_keyboard(user_id, active_tab="reserved_list"),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Tab 5: Lotto Status (Admin)
    elif action == "tab_status":
        avail, res = get_stats()
        pct = (res / MAX_NUMBERS) * 100
        await query.edit_message_text(
            f"--- 📊 **TAB: DASHBOARD** ---\n\n"
            f"• Total Tickets: {MAX_NUMBERS}\n"
            f"• Available: {avail}\n"
            f"• Reserved: {res}\n"
            f"• Sales Progress: {pct:.1f}%",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="status"),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def process_check_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Enter a number between 1 and {MAX_NUMBERS}:",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="check")
        )
        return WAITING_CHECK_NUM

    num = int(text)
    record = get_ticket(num)
    status_msg = f"🟢 Ticket #{num} is AVAILABLE!" if record and record["status"] == "available" else f"🔴 Ticket #{num} is RESERVED."
    
    await update.message.reply_text(status_msg, reply_markup=build_tabbed_keyboard(user_id, active_tab="check"))
    return ConversationHandler.END

async def process_reserve_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Admin action required.", reply_markup=build_tabbed_keyboard(user_id, active_tab="check"))
        return ConversationHandler.END

    if not text.isdigit() or not (1 <= int(text) <= MAX_NUMBERS):
        await update.message.reply_text(
            f"⚠️ Enter a number between 1 and {MAX_NUMBERS}:",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="reserve")
        )
        return WAITING_RESERVE_NUM

    num = int(text)
    if reserve_ticket(num, user_id):
        await update.message.reply_text(
            f"✅ Ticket #{num} successfully reserved in PostgreSQL!",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="reserve")
        )
    else:
        await update.message.reply_text(
            f"⚠️ Ticket #{num} is already reserved!",
            reply_markup=build_tabbed_keyboard(user_id, active_tab="reserve")
        )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.", reply_markup=build_tabbed_keyboard(update.effective_user.id, active_tab="check"))
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
        entry_points=[CallbackQueryHandler(tab_switch_handler)],
        states={
            WAITING_CHECK_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_check_number)],
            WAITING_RESERVE_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_reserve_number)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🚀 Tabbed Bot running with PostgreSQL persistence...")
    app.run_polling()

if __name__ == "__main__":
    main()
