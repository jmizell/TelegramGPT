import logging
import os
import sqlite3
import base64
import json
from telegram import ForceReply, Update, User
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import openai
import tiktoken

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-3.5-turbo-16k")
ALLOWED_USERS = json.loads(os.getenv("ALLOWED_USERS", "[]"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def num_tokens_from_string(string: str, model_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def create_table():
    """Create SQLite table if it doesn't exist."""
    with sqlite3.connect('chat_history.db') as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT,
            base64_message TEXT
        );
        """)
        conn.commit()


def add_message_to_db(user_id: int, role: str, message: str, conn):
    """Add a message to the database."""
    base64_message = base64.b64encode(message.encode()).decode()
    conn.execute("INSERT INTO chat_history (user_id, role, base64_message) VALUES (?, ?, ?)",
                 (str(user_id), role, base64_message))
    conn.commit()


def get_messages(user_id: int, max_tokens: int, model_name: str, conn):
    """Retrieve messages based on token count."""
    cursor = conn.execute(
        "SELECT * FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC", (str(user_id),))
    rows = cursor.fetchall()

    total_tokens = 0
    messages = []

    for row in rows:
        decoded_message = base64.b64decode(row['base64_message']).decode()
        tokens = num_tokens_from_string(decoded_message, model_name)

        if total_tokens + tokens <= max_tokens:
            messages.append((row['role'], decoded_message, tokens))
            total_tokens += tokens
        else:
            break

    return messages


def is_allowed(user: User) -> bool:
    """Checks to see if a user is allowed"""
    return user.id in ALLOWED_USERS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    logger.info(f"user={update.effective_user}, chat={update.effective_chat}, start")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return
    await update.message.reply_html(
        rf"Hi {update.effective_user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    logger.info(f"user={update.effective_user}, chat={update.effective_chat}, help")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return
    await update.message.reply_text("Help!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process chat message."""

    logger.info(f"user={update.effective_user}, chat={update.effective_chat}, chat")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return

    try:
        token_count = num_tokens_from_string(update.message.text, MODEL_NAME)
        if token_count > int(MAX_TOKENS / 2):
            await update.message.reply_text(f"Message token count {token_count} exceeds max token limit {MAX_TOKENS / 2}")
            return

        prompt = "You're a helpful assistant. You provide concise answers unless prompted for more detail. You avoid providing lists, or advice unprompted."
        used_tokens = token_count + num_tokens_from_string(prompt, MODEL_NAME)
        messages = [
            {"role": "system", "content": prompt},
        ]
        for msg in get_messages(update.effective_user.id, int(MAX_TOKENS*0.75)-token_count, MODEL_NAME, conn):
            messages.append({"role": msg[0], "content": msg[1]})
            used_tokens = used_tokens + msg[2]
        messages.append({"role": "user", "content": update.message.text})
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, used_tokens={used_tokens}, chat={json.dumps(messages, indent=3, sort_keys=True)}")

        response = openai.ChatCompletion.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0,
            max_tokens=MAX_TOKENS-used_tokens,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        add_message_to_db(update.effective_user.id, "user", update.message.text, conn)
        response_role = response["choices"][0]["message"]["role"]
        response_text = response["choices"][0]["message"]["content"]
        add_message_to_db(update.effective_user.id, response_role, response_text, conn)
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, response={response_text}")

        await update.message.reply_text(response_text)
    except Exception as oops:
        error_message = f"An error occurred: {str(oops)}"
        logger.error(error_message)
        await update.message.reply_text(error_message)


def main() -> None:
    """Start the bot."""
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_KEY")).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    create_table()
    with sqlite3.connect('chat_history.db') as conn:
        conn.row_factory = sqlite3.Row
        main()
