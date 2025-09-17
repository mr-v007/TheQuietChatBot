import os
import telebot
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === SECURE CONFIG (FROM ENVIRONMENT VARIABLES) ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_URL = os.getenv("SHEET_URL")
GOOGLE_SHEET_CREDENTIALS_JSON = eval(os.getenv("GOOGLE_CREDENTIALS_JSON"))
# ==================================================

# Initialize bot
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_SHEET_CREDENTIALS_JSON, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(SHEET_URL).sheet1

# Constants
FREE_TRIAL_END = datetime(2025, 9, 25, 23, 59, 59)
FREE_MSG_LIMIT = 5
PAYMENT_PRICE = 1  # ₹1

# User state tracking
user_states = {}

def get_user_data(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "msgs_today": 0,
            "paid_until": None,
            "last_msg_time": None
        }
    return user_states[user_id]

def log_to_sheet(user_id, date, msgs_used, paid_for_24h, paid_at=None, expires_at=None, blocked=False):
    row = [user_id, date, msgs_used, paid_for_24h, paid_at or "", expires_at or "", "Yes" if blocked else "No"]
    sheet.append_row(row)

def is_free_trial_active():
    return datetime.now() < FREE_TRIAL_END

def reset_daily_count(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    user_data = get_user_data(user_id)
    user_data["msgs_today"] = 0
    user_data["paid_until"] = None
    log_to_sheet(user_id, today, 0, False)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Anonymous"
    
    if is_free_trial_active():
        bot.reply_to(message, f"👋 Welcome, {user_name}!\n\n✨ You're in the FREE WEEK (until April 12, 2025)!\nTalk as much as you want — no limits.\n\nSomeone is waiting to hear your thoughts.")
    else:
        reset_daily_count(user_id)
        bot.reply_to(message, f"👋 Welcome, {user_name}!\n\n💬 You have 5 free messages today.\nAfter that, pay ₹1 to unlock 24 hours of unlimited chatting.\n\nSomeone is waiting to hear your thoughts.")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if not text:
        return
    
    if len(text.split()) < 3:
        bot.reply_to(message, "Please type at least 3 words so we can match you meaningfully. 😊")
        return
    
    blocked_words = [
        "pic", "photo", "insta", "instagram", "call", "date", "sexy", "hot",
        "sister", "babe", "fuck", "sex", "nude", "kiss", "love you", "meet",
        "number", "phone", "snapchat", "whatsapp", ".com", "http", "www", "@"
    ]
    if any(word in text.lower() for word in blocked_words):
        bot.reply_to(message, "🚫 This content isn't allowed here. Keep our space safe. ❤️")
        log_to_sheet(user_id, datetime.now().strftime("%Y-%m-%d"), 0, False, blocked=True)
        return

    user_data = get_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if user_data["last_msg_time"] and user_data["last_msg_time"].split()[0] != today:
        reset_daily_count(user_id)
        user_data["last_msg_time"] = today

    if user_data["paid_until"]:
        paid_until = datetime.strptime(user_data["paid_until"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() < paid_until:
            user_data["last_msg_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bot.reply_to(message, "✅ You have 24-hour unlimited access. Talk freely.")
            return
        else:
            user_data["paid_until"] = None

    if is_free_trial_active():
        user_data["last_msg_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bot.reply_to(message, "💬 You're in the free week — talk as much as you want!")
        return

    if user_data["msgs_today"] >= FREE_MSG_LIMIT:
        markup = telebot.types.InlineKeyboardMarkup()
        btn = telebot.types.InlineKeyboardButton("💰 Pay ₹1 for 24 Hours Unlimited", callback_data="pay_24h")
        markup.add(btn)
        bot.reply_to(message, 
            "⚠️ You've used your 5 free messages today.\n\nPay ₹1 to unlock 24 hours of unlimited chatting — no limits.\n\nThis is your quiet escape.", 
            reply_markup=markup)
        return

    user_data["msgs_today"] += 1
    user_data["last_msg_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_to_sheet(user_id, today, user_data["msgs_today"], False)
    bot.reply_to(message, "💬 Message sent. Someone is listening.")

@bot.callback_query_handler(func=lambda call: call.data == "pay_24h")
def handle_payment_button(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id, "Processing payment...")

    bot.send_invoice(
        chat_id=call.message.chat.id,
        title="Unlock 24 Hours of Unlimited Chatting",
        description="Pay ₹1 to get 24 continuous hours of unlimited anonymous texting.",
        provider_token="",  
        currency="INR",
        prices=[telebot.types.LabeledPrice(label="₹1 for 24h", amount=100)],
        payload=f"24h_access_{user_id}",
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Payment failed. Try again.")

@bot.message_handler(content_types=['successful_payment'])
def successful_payment(message):
    user_id = message.from_user.id
    payment_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    
    user_data = get_user_data(user_id)
    user_data["paid_until"] = expires_at
    user_data["msgs_today"] = 0
    
    log_to_sheet(
        user_id,
        datetime.now().strftime("%Y-%m-%d"),
        0,
        True,
        paid_at=payment_date,
        expires_at=expires_at
    )
    
    bot.send_message(
        message.chat.id,
        "🎉 Congratulations! You’ve unlocked 24 hours of unlimited chatting.\n\nSend any message to start talking.\nYour access expires at:\n" + expires_at
    )

if __name__ == "__main__":
    bot.polling(none_stop=True)
