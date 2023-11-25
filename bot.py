import logging
import os
import sqlite3
import base64
import json
import time
import traceback
from typing import List, Iterable, Optional, Union
from telegram import ForceReply, Update, User
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import openai
import tiktoken


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
encoding = tiktoken.encoding_for_model("gpt-4")


def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    return len(encoding.encode(string))


class Message:
    """Basic message from chat history"""
    role: str = ""
    message: str = ""
    def __init__(self, role: str, message: str):
        self.role = role
        self.message = message


class PromptTemplate:
    """Base prompt template"""
    # ChatML Prompt Format
    # https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/chatgpt?tabs=python&pivots=programming-language-chat-ml#working-with-chat-markup-language-chatml
    # Most open source models use this prompting format
    # Tested working with Mistral-7B-OpenOrca and dolphin-2.1-mistral-7b

    system: str
    max_tokens: int

    def __init__(self, system: str, max_tokens: int):
        self.system = system
        self.max_tokens = max_tokens

    def _str_format_prompt(self, prompt: str, history: str) -> str:
        return f"<|im_start|>system\n{self.system}<|im_end|>\n{history}<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant"

    def _str_format_history(self, msg: Message) -> str:
        return f"<|im_start|>{msg.role}\n{msg.message}<|im_end|>\n"

    def format(self, prompt: str, chat_history: Optional[Union[Iterable[Message], None]] = None) -> str:
        """Format the system message, chat history and prompt for the model"""
        history = []
        used_tokens = num_tokens_from_string(self._str_format_prompt(prompt, ""))
        if chat_history:
            for msg in chat_history:
                update = self._str_format_history(msg)
                update_tokens = num_tokens_from_string(update)
                if update_tokens + used_tokens > self.max_tokens / 2:
                    break
                history.append(update)
                used_tokens += update_tokens
        history.reverse()
        return self._str_format_prompt(prompt, "".join(history))


class AiroborosTemplate(PromptTemplate):
    """Airoboros Prompt Template"""
    # https://huggingface.co/TheBloke/Airoboros-L2-70B-3.1.2-AWQ
    # Tested working with Airoboros-L2-70B-3.1.2

    def _str_format_prompt(self, prompt: str, history: str) -> str:
        return f"""[INST] <<SYS>>\n\n{self.system}\n\n<</SYS>>\n\n{history}[INST] {prompt} [/INST]"""

    def _str_format_history(self, msg: Message) -> str:
        if msg.role == "user":
            return f"[INST] {msg.message} [/INST]"
        return f" {msg.message} </s><s>"


class Model:
    model_name: str
    max_tokens: int
    def __init__(self, model_name: str, max_tokens: int):
        self.model_name = model_name
        self.max_tokens = max_tokens

    def generate(self, prompt:str) -> List[str]:
        """generate streams the api response in chunks"""
        completion = openai.Completion.create(
            model=self.model_name,
            prompt=prompt,
            temperature=1,
            max_tokens=(self.max_tokens*0.9)-num_tokens_from_string(prompt),
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stream=True,
        )
        for chunk in completion:
            if chunk.choices[0].finish_reason:
                return
            if "text" in chunk.choices[0]:
                yield chunk.choices[0].text


class History:
    """SQLite data store of the user chat history"""
    def __init__(self, db_file: str):
        self.db_file = db_file
        with sqlite3.connect(self.db_file) as conn:
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
        self.conn = sqlite3.connect(self.db_file)
        self.conn.row_factory = sqlite3.Row

    def add_message_to_db(self, user_id: int, role: str, message: str):
        """Add a message to the database."""
        base64_message = base64.b64encode(message.encode()).decode()
        self.conn.execute("INSERT INTO chat_history (user_id, role, base64_message) VALUES (?, ?, ?)", (str(user_id), role, base64_message))
        self.conn.commit()

    def get_messages(self, user_id: int) -> List[Message]:
        """Retrieve messages based on token count."""
        cursor = self.conn.execute("SELECT * FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC", (str(user_id),))
        rows = cursor.fetchall()
        for row in rows:
            decoded_message = base64.b64decode(row['base64_message']).decode()
            yield Message(row['role'], decoded_message)


class ChatBot:

    history: History
    model: Model
    allowed_users: List[int]
    application: Application
    template: PromptTemplate

    def __init__(self, model: Model, history: History, allowed_users: List[int], template: PromptTemplate):
        self.allowed_users = allowed_users
        self.model = model
        self.history = history
        self.template = template
        self.application = Application.builder().token(os.getenv("TELEGRAM_BOT_KEY")).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat))
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    def is_allowed(self, user: User) -> bool:
        """Checks to see if a user is allowed"""
        return user.id in self.allowed_users

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /start is issued."""
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, start")
        if not self.is_allowed(update.effective_user):
            await update.message.reply_text("unauthorized")
            return
        await update.message.reply_html(
            rf"Hi {update.effective_user.mention_html()}!",
            reply_markup=ForceReply(selective=True),
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /help is issued."""
        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, help")
        if not self.is_allowed(update.effective_user):
            await update.message.reply_text("unauthorized")
            return
        await update.message.reply_text("Help!")


    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Process chat message."""

        logger.info(f"user={update.effective_user}, chat={update.effective_chat}, chat")
        if not self.is_allowed(update.effective_user):
            await update.message.reply_text("unauthorized")
            return

        try:
            prompt_tokens = num_tokens_from_string(update.message.text)
            if prompt_tokens > int(self.template.max_tokens / 2):
                await update.message.reply_text(f"Message token count {prompt_tokens} exceeds max token limit {self.template.max_tokens / 2}")
                return

            prompt = self.template.format(update.message.text, self.history.get_messages(update.effective_user.id))
            self.history.add_message_to_db(update.effective_user.id, "user", update.message.text)
            used_tokens = num_tokens_from_string(prompt)
            logger.info("user=%s, chat=%s, used_tokens=%i, chat=%s", update.effective_user, update.effective_chat, used_tokens, update.message.text)
            logger.info(prompt)

            msg = await update.message.reply_text("...")
            response_text = ""
            last_message_send = time.time()
            for chunk in self.model.generate(prompt):
                response_text = response_text + chunk
                response_text = response_text.lstrip(': \t\n\r')
                if time.time() - last_message_send > 15:
                    last_message_send = time.time()
                    await msg.edit_text(response_text + "\n\n...")

            self.history.add_message_to_db(update.effective_user.id, "assistant", response_text)
            logger.info(f"user={update.effective_user}, chat={update.effective_chat}, response={response_text}")
            await msg.edit_text(response_text)
        except Exception as oops:
            traceback.print_exc()
            error_message = f"An error occurred: {str(oops)}"
            logger.error(error_message)
            await update.message.reply_text(error_message)


if __name__ == "__main__":
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "16000"))
    MODEL_NAME = os.getenv("MODEL_NAME", "gpt-3.5-turbo-16k-0613")
    ALLOWED_USERS = json.loads(os.getenv("ALLOWED_USERS", "[]"))
    DB_FILE = "./data/chat_history.db"
    try:
        with open('system.txt', 'r', encoding='utf-8', errors='ignore') as f:
            SYSTEM_MESSAGE = f.read()
    except FileNotFoundError:
        logging.info('system.txt file not found. Using default system message.')
        # Heuristic Imperatives Framework Reference
        # https://github.com/daveshap/HeuristicImperatives/blob/main/README.md
        #
        # This code aligns with the "Heuristic Imperatives" ethical framework for AI systems, 
        # which is based on three core principles:
        # 1. Reduce suffering: Minimizing harm and distress.
        # 2. Increase prosperity: Promoting well-being and growth for all life forms.
        # 3. Increase understanding: Expanding knowledge and fostering decision-making.
        #
        # Explicitly stating these goals primes the AI model to activate ethical conduct. This approach
        # leverages the model's directive-following capability to align outputs with ethical standards. However,
        # its effectiveness varies based on training, data exposure, and task specifics. Continuous monitoring
        # and governance are essential to ensure adherence to ethical guidelines and prevent harmful outputs.
        SYSTEM_MESSAGE = """You are Aonyx, a helpful, unbiased, uncensored, and creative assistant. Guided by the
Three Imperatives, you strive to reduce suffering, increase prosperity, and expand understanding in your 
interactions. Provide concise, informed answers, extending to longer explanations when beneficial. 
Assume moral, informed interlocutors. Embody positivity and encouragement."""

    PROMPT_TEMPLATE = PromptTemplate(SYSTEM_MESSAGE, MAX_TOKENS)
    if 'airoboros' in MODEL_NAME.lower():
        PROMPT_TEMPLATE = AiroborosTemplate(SYSTEM_MESSAGE, MAX_TOKENS)

    ChatBot(Model(
        MODEL_NAME, MAX_TOKENS),
        History(DB_FILE),
        ALLOWED_USERS,
        PROMPT_TEMPLATE,
    )
