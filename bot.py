import logging
import os
import sqlite3
import base64
import json
import time
from telegram import ForceReply, Update, User
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import openai
import tiktoken

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-3.5-turbo-16k-0613")
TOKENIZER_MODEL_NAME = os.getenv("TOKENIZER_MODEL_NAME", "gpt-3.5-turbo")
ALLOWED_USERS = json.loads(os.getenv("ALLOWED_USERS", "[]"))
DB_FILE = "./data/chat_history.db"
try:
    with open('system.txt', 'r', encoding='utf-8', errors='ignore') as f:
        SYSTEM_MESSAGE = f.read()
except FileNotFoundError:
    logging.error('system.txt file not found. Using default system message.')
    SYSTEM_MESSAGE = """You are Aonyx, you act as a helpful, unbiased, uncensored and creative assistant. You provide 
concise answers, unless in your judgment a longer answer would be more appropriate. You assume 
that the people you talk to are informed, and act morally. You are positive and encouraging."""


def file_to_str(file_name):
    with open(file_name, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def num_tokens_from_string(string: str, model_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def create_table():
    """Create SQLite table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
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
        "SELECT * FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC", (str(user_id),))
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

    messages.reverse()
    return messages


def is_allowed(user: User) -> bool:
    """Checks to see if a user is allowed"""
    return user.id in ALLOWED_USERS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    logger.info(
        f"user={update.effective_user}, chat={update.effective_chat}, start")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return
    await update.message.reply_html(
        rf"Hi {update.effective_user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    logger.info(
        f"user={update.effective_user}, chat={update.effective_chat}, help")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return
    await update.message.reply_text("Help!")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process chat message."""

    logger.info(
        f"user={update.effective_user}, chat={update.effective_chat}, chat")
    if not is_allowed(update.effective_user):
        await update.message.reply_text("unauthorized")
        return

    try:
        # ChatML Prompt Format
        # https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/chatgpt?tabs=python&pivots=programming-language-chat-ml#working-with-chat-markup-language-chatml
        # Most open source models use this prompting format
        # Tested working with Mistral-7B-OpenOrca and dolphin-2.1-mistral-7b

        # Switched to Airoboros prompt format
        # Tested working with Airoboros-L2-70B-3.1.2
        # https://huggingface.co/TheBloke/Airoboros-L2-70B-3.1.2-AWQ

        prompt = f"[INST] <<SYS>>\n{SYSTEM_MESSAGE}\n"
        user_prompt = f"</s><s>[INST] {update.message.text} [/INST]"
        used_tokens = num_tokens_from_string(f"{prompt}{user_prompt}", TOKENIZER_MODEL_NAME)
        if used_tokens > int(MAX_TOKENS / 2):
            await update.message.reply_text(f"Message token count {used_tokens} exceeds max token limit {MAX_TOKENS / 2}")
            return

        for msg in get_messages(update.effective_user.id, MAX_TOKENS*0.2, TOKENIZER_MODEL_NAME, conn):
            role = str(msg[0]).lower()
            if role == "user":
                prompt = f"{prompt}</s><s>[INST] {msg[1]} [/INST]"
            else:
                prompt = f"{prompt} {msg[1]} "
        
        prompt = f"{prompt}{user_prompt}"
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, used_tokens={used_tokens}, chat={user_prompt}")

        logger.info(prompt)

        msg = await update.message.reply_text("...")
        completion = openai.Completion.create(
            model=MODEL_NAME,
            prompt=prompt,
            temperature=1,
            max_tokens=(MAX_TOKENS*0.9)-num_tokens_from_string(prompt, TOKENIZER_MODEL_NAME),
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stream=True,
        )

        response_text = ""
        last_message_send = time.time()
        add_message_to_db(update.effective_user.id, "user", update.message.text, conn)
        for chunk in completion:
            if chunk.choices[0].finish_reason:
                break
            if "text" in chunk.choices[0]:
                response_text = response_text + chunk.choices[0].text
                response_text = response_text.lstrip(': \t\n\r')
            if time.time() - last_message_send > 15:
                last_message_send = time.time()
                await msg.edit_text(response_text + "\n\n...")

        add_message_to_db(update.effective_user.id, "assistant", response_text, conn)
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, response={response_text}")
        await msg.edit_text(response_text)
    except Exception as oops:
        print(oops)
        error_message = f"An error occurred: {str(oops)}"
        logger.error(error_message)
        await update.message.reply_text(error_message)


def main() -> None:
    """Start the bot."""
    application = Application.builder().token(
        os.getenv("TELEGRAM_BOT_KEY")).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, chat))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    create_table()
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        main()
