"""
Nebula Kirana Store — AI Operations Agent
Telegram Bot Entry Point

Run: python main.py
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

# Initialize DB on startup
from db.database import engine
from db.models import Base
from db.seed import run as seed_db

Base.metadata.create_all(bind=engine)
seed_db()

from agent.session import get_session, reset_session, transcribe_audio

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nebula-bot")

# ── Ensure Single Bot Instance (Kill Zombies/Orphans) ─────────────────────────
try:
    import psutil
    _cur_pid = os.getpid()
    for _proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if _proc.info["pid"] != _cur_pid:
                _cmd = " ".join(_proc.info["cmdline"] or [])
                if "main.py" in _cmd and "python" in (_proc.info["name"] or "").lower():
                    logger.info(f"Terminating conflicting bot instance PID={_proc.info['pid']}")
                    _proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
except Exception as _e:
    logger.warning(f"Could not scan processes: {_e}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# ── Command Handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command — welcome message."""
    chat_id = str(update.effective_chat.id)
    reset_session(chat_id)

    welcome = (
        "*Nebula Kirana Store* — AI Operations Manager 🛒\n\n"
        "I'm ready to help you manage your store via **Text or Voice**!\n\n"
        "*What I can do:*\n"
        "- 📦 **Inventory** — stock checks, reorder alerts, restock\n"
        "- 🧾 **Billing** — instant bills with GST & PDF invoices\n"
        "- 📒 **Khata (Credit)** — customer credit ledger & settlements\n"
        "- 📊 **Analytics** — daily closing reports & PowerPoint decks\n"
        "- 🎙️ **Voice Notes** — send a voice message in any Indian language or English!\n\n"
        "_Tip: You can speak or type in any language (English, Hindi, Tamil, Telugu, Kannada, etc.) and I will always assist you in clear English._\n\n"
        "_Examples:_\n"
        "`50 packets of Maggi received`\n"
        "`Make a bill: 2 Maggi, 1 Atta, paid by UPI`\n"
        "`Add Rs 500 credit for Ramesh`\n"
        "`Show today's closing report`\n\n"
        "Type /help to see all commands."
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new — reset conversation history (data stays in DB)."""
    chat_id = str(update.effective_chat.id)
    reset_session(chat_id)
    await update.message.reply_text(
        "🔄 New conversation started! Your data is safe — I've just cleared the chat history.\n"
        "How can I help?"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "*Nebula Store - Command Guide*\n\n"
        "*Commands:*\n"
        "/start - Welcome and reset\n"
        "/new - Clear conversation history\n"
        "/help - Show this guide\n\n"
        "*Inventory:*\n"
        "`50 packets of Maggi received` - Add stock\n"
        "`How much Maggi do we have?` - Check stock\n"
        "`What needs to be reordered?` - Low stock list\n"
        "`Add new product Horlicks 500g MRP 265` - Add product\n\n"
        "*Billing:*\n"
        "`Make a bill: 2 Maggi, 1 Atta, UPI` - Quick bill\n"
        "`Add 3 Surf Excel to the bill` - Add to open bill\n"
        "`Remove Maggi from bill` - Edit bill\n"
        "`Show current bill` - Preview with GST breakdown\n"
        "`Finalize the bill` - Save and confirm\n"
        "`Send PDF invoice` - Get GST invoice as PDF\n\n"
        "*Credit (Khata):*\n"
        "`Add Rs 500 credit for Ramesh` - Record credit\n"
        "`Ramesh paid Rs 300` - Record payment\n"
        "`What is Ramesh's balance?` - Check balance\n"
        "`Show all outstanding credit` - All customers\n\n"
        "*Reports:*\n"
        "`Today's closing report` - Daily summary\n"
        "`Generate weekly analysis deck` - PPTX report\n\n"
        "*Settings:*\n"
        "`Set default payment to UPI` - Save preference\n"
        "`My GSTIN is 29AAAXX...` - Save GSTIN\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ── Main Message Handler ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all text messages through the Gemini agent."""
    chat_id = str(update.effective_chat.id)
    user_text = update.message.text

    if not user_text or not user_text.strip():
        return

    logger.info(f"[{chat_id}] User: {user_text[:80]}")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        session = get_session(chat_id)

        # Run the Gemini call in a thread (it's synchronous)
        loop = asyncio.get_event_loop()
        response_text, pending_files = await loop.run_in_executor(
            None, session.send, user_text
        )

        # Send any generated files (PDF, PPTX) first
        for filepath in pending_files:
            path = Path(filepath)
            if path.exists():
                logger.info(f"[{chat_id}] Sending file: {path.name}")
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action="upload_document",
                )
                with open(path, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=path.name,
                        caption=f"📎 {path.name}",
                    )

        # Send the text response
        if response_text and response_text.strip():
            # Split long responses if needed (Telegram 4096 char limit)
            if len(response_text) <= 4096:
                await update.message.reply_text(response_text)
            else:
                # Split at newlines to avoid cutting mid-word
                chunks = _split_message(response_text, 4000)
                for chunk in chunks:
                    await update.message.reply_text(chunk)

        logger.info(f"[{chat_id}] Response sent ({len(response_text or '')} chars, {len(pending_files)} files)")

    except Exception as e:
        logger.error(f"[{chat_id}] Error: {e}", exc_info=True)

        error_msg = (
            "⚠️ Something went wrong processing your request. Please try again.\n"
            "If the issue persists, use /new to reset the conversation."
        )

        # More specific error messages
        if "quota" in str(e).lower() or "429" in str(e):
            error_msg = "⏳ API rate limit hit. Please wait a moment and try again."
        elif "not found" in str(e).lower() and "model" in str(e).lower():
            error_msg = "⚠️ AI model error. Please try again in a few seconds."

        await update.message.reply_text(error_msg)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice notes and audio clips by transcribing via Groq Whisper and processing query."""
    chat_id = str(update.effective_chat.id)
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    logger.info(f"[{chat_id}] Voice/Audio received: duration={getattr(voice, 'duration', '?')}s")

    # Show typing action
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    temp_dir = Path("output/audio_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"voice_{update.update_id}_{chat_id}.ogg"

    try:
        tg_file = await voice.get_file()
        await tg_file.download_to_drive(custom_path=temp_file)

        # Transcribe in executor thread
        loop = asyncio.get_event_loop()
        transcribed_text = await loop.run_in_executor(
            None, transcribe_audio, str(temp_file)
        )

        if not transcribed_text or not transcribed_text.strip():
            await update.message.reply_text("🎙️ Sorry, I could not hear any clear speech in the voice note. Please try speaking again.")
            return

        logger.info(f"[{chat_id}] Transcribed: {transcribed_text}")
        
        # Send transcript acknowledgment
        await update.message.reply_text(f"🎤 *Heard:* _{transcribed_text}_", parse_mode="Markdown")

        # Process query through agent session
        session = get_session(chat_id)
        response_text, pending_files = await loop.run_in_executor(
            None, session.send, transcribed_text
        )

        # Send any generated files (PDF, PPTX) first
        for filepath in pending_files:
            path = Path(filepath)
            if path.exists():
                logger.info(f"[{chat_id}] Sending file: {path.name}")
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action="upload_document",
                )
                with open(path, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=path.name,
                        caption=f"📎 {path.name}",
                    )

        # Send text response
        if response_text and response_text.strip():
            if len(response_text) <= 4096:
                await update.message.reply_text(response_text)
            else:
                chunks = _split_message(response_text, 4000)
                for chunk in chunks:
                    await update.message.reply_text(chunk)

        logger.info(f"[{chat_id}] Voice response sent ({len(response_text or '')} chars, {len(pending_files)} files)")

    except Exception as e:
        logger.error(f"[{chat_id}] Voice processing error: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Could not process the voice note. Please try speaking again or type your message.")
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


def _split_message(text: str, max_len: int) -> list[str]:
    """Split a long message into chunks at newline boundaries."""
    chunks = []
    current = []
    current_len = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > max_len and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


# ── Bot Setup & Run ───────────────────────────────────────────────────────────

async def post_init(application: Application):
    """Set bot commands after startup."""
    commands = [
        BotCommand("start", "Start the bot & reset conversation"),
        BotCommand("new", "Clear conversation history"),
        BotCommand("help", "Show all commands & examples"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Bot commands registered.")


def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file!")

    logger.info("🚀 Starting Nebula Kirana Store Bot...")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    logger.info("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
