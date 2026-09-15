"""
Starz Promosyon — Telegram information bot.

Purpose
-------
Sends general news-style updates, useful information, educational content
and technology information to users who have sent /start.

Design rules followed
---------------------
* Uses ONLY the Telegram Bot API (long polling). No external APIs,
  no databases, no third-party services, no paid services.
* The bot token is read from the environment variable BOT_TOKEN
  (set in Railway → Variables). It is never hardcoded.
* Subscribers are kept in memory only. A Railway restart clears the list,
  and users simply send /start again.
* A 10-minute asyncio loop inside THIS process sends the updates.
  There is no cron job and no separate scheduler service.
* Every outgoing item passes a local safety filter that blocks
  gambling, financial promotion, politics, medical promotion,
  weapons, adult content, hate, violence, clickbait and similar topics.
* The bot never claims to provide live breaking news.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from telegram import Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("starz-promosyon")

# httpx / httpcore log the full request URL, which contains the bot token.
# Keep them at WARNING so the token never appears in Railway logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The token is read from the environment.
# On Railway:  Project → Variables → add  BOT_TOKEN = <your token>
# NEVER hardcode the token here and never commit it to GitHub.
BOT_TOKEN = os.getenv("BOT_TOKEN")

# How often automatic updates are sent.
UPDATE_INTERVAL_SECONDS = 10 * 60  # 10 minutes

# Small pause between messages. Telegram allows roughly 30 messages/second
# to different chats; this keeps us far below that limit.
SEND_PACING_SECONDS = 0.05


# ---------------------------------------------------------------------------
# In-memory subscriber list
# ---------------------------------------------------------------------------
# Only the chat IDs of users who sent /start are stored, and only in RAM.
# A Railway restart / redeploy clears this list — users then send /start
# again to re-subscribe. No database is used.
subscribers: set[int] = set()


# ---------------------------------------------------------------------------
# User-facing text
# ---------------------------------------------------------------------------
WELCOME_TEXT = (
    "Welcome to Starz Promosyon.\n\n"
    "Get clear and easy-to-read news, useful information, technology "
    "updates, educational facts, and general world information.\n\n"
    "You can receive updates directly here on Telegram."
)

STOP_TEXT = (
    "Automatic updates have been stopped.\n\n"
    "Send /start at any time to turn them back on."
)

HELP_TEXT = (
    "Available commands:\n\n"
    "/start — subscribe to automatic updates\n"
    "/stop — stop automatic updates\n"
    "/help — show this message\n"
    "/about — information about this bot"
)

ABOUT_TEXT = (
    "Starz Promosyon shares general news-style updates, useful information, "
    "educational content, technology information and general-interest "
    "stories.\n\n"
    "The content is original and written to stay neutral, factual and "
    "non-promotional. The bot does not cover gambling, financial promotion, "
    "politics, medical advice or other restricted topics, and it does not "
    "claim to provide live breaking news.\n\n"
    "Automatic updates are sent roughly every 10 minutes to users who have "
    "sent /start."
)

FOOTER = "Starz Promosyon — useful information in one place."


# ---------------------------------------------------------------------------
# Built-in content library
# ---------------------------------------------------------------------------
# All items below are original, generic and educational.
# They contain no live news, no dates, no statistics, no named people or
# organisations, no links and no copied text. They are intentionally
# timeless so the bot never pretends to have a live news source.
CONTENT_LIBRARY: list[dict] = [
    {
        "title": "Technology Update",
        "body": (
            "Digital tools continue to change how people learn, communicate "
            "and manage everyday tasks. Learning a few basic digital skills "
            "can help users work more efficiently and make better use of "
            "online services."
        ),
    },
    {
        "title": "Internet Safety Note",
        "body": (
            "Strong passwords usually combine length, variety and uniqueness. "
            "Reusing the same password across many accounts increases risk if "
            "one service is ever affected. A password manager can help keep "
            "track of different logins."
        ),
    },
    {
        "title": "Digital Literacy Tip",
        "body": (
            "Two-factor authentication adds a second step when signing in. "
            "Even if a password becomes known to someone else, the extra step "
            "makes access harder. Many online services offer this option in "
            "their security settings."
        ),
    },
    {
        "title": "Science Note",
        "body": (
            "Water moves continuously between oceans, the atmosphere and "
            "land. It evaporates, forms clouds, falls as rain or snow, and "
            "then flows back. This cycle supports agriculture, rivers and "
            "everyday life."
        ),
    },
    {
        "title": "Education Tip",
        "body": (
            "Reviewing information over several short sessions often works "
            "better than studying everything at once. This approach, "
            "sometimes called spaced practice, helps memory last longer."
        ),
    },
    {
        "title": "Environmental Note",
        "body": (
            "Recycling helps reduce the amount of material sent to landfills. "
            "Separating paper, glass, metal and certain plastics makes the "
            "process easier. Local guidelines usually explain what can and "
            "cannot be recycled."
        ),
    },
    {
        "title": "General Knowledge",
        "body": (
            "The Earth rotates, so different regions experience daylight at "
            "different moments. Time zones were introduced to give nearby "
            "areas a shared clock. They help travel, trade and communication "
            "run more smoothly."
        ),
    },
    {
        "title": "Historical Note",
        "body": (
            "Before mechanical printing, books were copied by hand. The "
            "arrival of the printing press made written material easier to "
            "reproduce. Over time, this helped spread literacy and ideas "
            "more widely."
        ),
    },
    {
        "title": "Technology Update",
        "body": (
            "Cloud storage allows files to be kept on remote servers and "
            "opened from different devices. It is commonly used for photos, "
            "documents and backups. A strong password and two-factor "
            "authentication help protect an account."
        ),
    },
    {
        "title": "Digital Literacy Tip",
        "body": (
            "Some messages try to look like they come from a trusted service "
            "and ask for personal details or a quick click. Checking the "
            "sender, avoiding unknown links and verifying through official "
            "channels can reduce the chance of being misled."
        ),
    },
    {
        "title": "Science Note",
        "body": (
            "Plants use sunlight, water and carbon dioxide to make their own "
            "food. This process, called photosynthesis, also releases oxygen. "
            "It supports most life on Earth."
        ),
    },
    {
        "title": "Education Tip",
        "body": (
            "Writing short summaries in your own words can make new "
            "information easier to remember. Notes work well when they are "
            "simple, organised and reviewed soon after a lesson or reading."
        ),
    },
    {
        "title": "Environmental Note",
        "body": (
            "Sources such as sunlight, wind and moving water can be used to "
            "generate electricity. They are naturally replenished and are "
            "used in many parts of the world alongside other energy sources."
        ),
    },
    {
        "title": "General Knowledge",
        "body": (
            "The metric system uses units such as metre, litre and gram. Its "
            "structure is based on powers of ten, which makes conversion "
            "between units straightforward. It is widely used in science and "
            "in many countries for everyday measurement."
        ),
    },
    {
        "title": "Internet Safety Note",
        "body": (
            "Keeping software up to date, using trusted websites and avoiding "
            "unknown downloads can help reduce online risks. Public Wi-Fi "
            "networks are convenient but are safer when used with encrypted "
            "connections."
        ),
    },
    {
        "title": "Technology Update",
        "body": (
            "Open source software is developed with publicly available code. "
            "Anyone can read, study and often contribute to it. It powers "
            "many tools used for learning, programming and everyday "
            "computing."
        ),
    },
    {
        "title": "Science Note",
        "body": (
            "Sleep supports memory, mood and overall wellbeing. Regular sleep "
            "and wake times, along with a calm environment before bed, are "
            "often recommended for better rest."
        ),
    },
    {
        "title": "Education Tip",
        "body": (
            "Reading a little each day can widen vocabulary and improve "
            "understanding of written material. Short articles, stories or "
            "informative pieces all count. The habit matters more than the "
            "length of each session."
        ),
    },
    {
        "title": "Environmental Note",
        "body": (
            "Simple habits such as fixing leaks, taking shorter showers and "
            "turning off taps can reduce water use. Saving water supports "
            "households and communities, especially in areas where supply is "
            "limited."
        ),
    },
    {
        "title": "General Knowledge",
        "body": (
            "Thousands of languages are spoken around the world. They carry "
            "culture, history and ways of thinking. Learning even a few "
            "phrases in another language can improve communication and "
            "understanding."
        ),
    },
    {
        "title": "Technology Update",
        "body": (
            "Digital maps combine location data with software to help people "
            "plan routes and find places. They are widely used for travel, "
            "delivery and everyday navigation. Accuracy depends on regularly "
            "updated information."
        ),
    },
    {
        "title": "Digital Literacy Tip",
        "body": (
            "Not every piece of information online is accurate. Checking the "
            "author, the date and the supporting details can help readers "
            "decide whether a source is reliable. Comparing several sources "
            "often gives a clearer picture."
        ),
    },
    {
        "title": "Science Note",
        "body": (
            "The solar system includes the Sun, planets, moons, asteroids "
            "and comets. Gravity keeps these objects in orbit. Studying the "
            "solar system helps researchers understand how planets form and "
            "change."
        ),
    },
    {
        "title": "Education Tip",
        "body": (
            "Asking questions while learning can reveal gaps in "
            "understanding. Reaching out to teachers, classmates or reliable "
            "references often leads to better answers than guessing."
        ),
    },
]


# ---------------------------------------------------------------------------
# Local safety filter
# ---------------------------------------------------------------------------
# Every outgoing item is checked against this list before it is sent.
# If any keyword matches, the item is skipped. The filter is deliberately
# conservative: when in doubt, do not send.
PROHIBITED_KEYWORDS: list[str] = [
    # 1. Gambling
    "casino", "casinos", "betting", "bet", "bets", "lottery", "lotteries",
    "gambling", "gamble", "wager", "wagering", "poker", "jackpot", "odds",
    "bookmaker", "bookmakers", "sportsbook", "roulette",

    # 2. Financial promotion
    "invest", "investing", "investment", "investments", "profit", "profits",
    "guaranteed return", "guaranteed returns", "crypto", "cryptocurrency",
    "forex", "trading signal", "trading signals", "loan", "loans",
    "payday loan", "get rich", "financial advice", "financial promotion",
    "financial solicitation", "quick money", "easy money", "passive income",

    # 3. Political promotion
    "election", "elections", "candidate", "candidates", "political party",
    "political parties", "political campaign", "campaign", "vote", "voting",
    "referendum", "political movement", "political", "politician",
    "politicians", "partisan",

    # 4. Religion as promotion
    "religious campaign", "religious movement", "religious persuasion",
    "religious promotion", "proselytising",

    # 5. Medical / health promotion
    "medicine", "medicines", "medication", "cure", "cures", "treatment",
    "treatments", "supplement", "supplements", "weight loss", "disease",
    "diseases", "medical guarantee", "health claim", "health claims",
    "miracle cure", "pharmacy", "pharmaceutical", "prescription",

    # 6. Drugs, alcohol, tobacco
    "alcohol", "tobacco", "cigarette", "cigarettes", "vape", "vaping",
    "drug", "drugs", "narcotic", "narcotics", "beer", "wine", "whiskey",
    "vodka", "brewery",

    # 7. Weapons
    "weapon", "weapons", "gun", "guns", "firearm", "firearms",
    "ammunition", "explosive", "explosives", "bomb", "bombs",
    "grenade", "grenades", "rifle", "pistol", "silencer",

    # 8. Sexual content
    "porn", "pornography", "sex", "sexual", "sexually", "adult service",
    "adult services", "escort", "escorts", "nsfw", "erotic",

    # 9. Violence / shocking material
    "gore", "gory", "murder", "murders", "kill", "kills", "killing",
    "violent", "violence", "blood", "bloody", "graphic accident",
    "graphic accidents", "massacre", "terrorist", "terrorism", "beheading",

    # 10. Hate / discrimination
    "hate speech", "racist", "racism", "discrimination", "harassment",
    "harass", "dehumanizing",

    # 11. Deceptive / clickbait
    "breaking news", "breaking", "shocking", "you won't believe",
    "urgent", "must see", "secret", "exclusive opportunity",
    "guaranteed", "number one", "clickbait", "click bait", "best",
    "sensational", "miracle",
]

# Precompile word-boundary regexes so we do not match substrings
# (e.g. "kill" must not match "skills", "bet" must not match "better").
_PROHIBITED_PATTERNS = [
    re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    for word in PROHIBITED_KEYWORDS
]


def is_content_safe(text: str) -> bool:
    """Return True only if the text contains no prohibited keyword."""
    if not text or not text.strip():
        return False
    for pattern in _PROHIBITED_PATTERNS:
        if pattern.search(text):
            logger.warning("Safety filter blocked content for pattern: %s",
                           pattern.pattern)
            return False
    return True


def _build_safe_pool() -> list[dict]:
    """Filter CONTENT_LIBRARY once at startup so only safe items remain."""
    pool: list[dict] = []
    for item in CONTENT_LIBRARY:
        combined = f"{item['title']}\n\n{item['body']}\n\n{FOOTER}"
        if is_content_safe(combined):
            pool.append(item)
    logger.info("Content pool ready: %d safe items out of %d.",
                len(pool), len(CONTENT_LIBRARY))
    return pool


SAFE_CONTENT: list[dict] = _build_safe_pool()


def format_item(item: dict) -> str:
    """Build the final message text for one content item."""
    return f"{item['title']}\n\n{item['body']}\n\n{FOOTER}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe the user to automatic updates."""
    chat = update.effective_chat
    if chat is None:
        return

    chat_id = chat.id
    already_subscribed = chat_id in subscribers

    if not already_subscribed:
        subscribers.add(chat_id)
        logger.info("New subscriber added. Total subscribers: %d", len(subscribers))

    text = WELCOME_TEXT
    if already_subscribed:
        text += "\n\nYou are already receiving automatic updates."

    try:
        await update.effective_message.reply_text(text)
    except TelegramError as err:
        logger.warning("Could not reply to /start: %s", type(err).__name__)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the user from automatic updates."""
    chat = update.effective_chat
    if chat is None:
        return

    chat_id = chat.id
    if chat_id in subscribers:
        subscribers.discard(chat_id)
        logger.info("Subscriber removed. Total subscribers: %d", len(subscribers))
        text = STOP_TEXT
    else:
        text = (
            "Automatic updates are already stopped for you.\n\n"
            "Send /start to enable them."
        )

    try:
        await update.effective_message.reply_text(text)
    except TelegramError as err:
        logger.warning("Could not reply to /stop: %s", type(err).__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.effective_message.reply_text(HELP_TEXT)
    except TelegramError as err:
        logger.warning("Could not reply to /help: %s", type(err).__name__)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.effective_message.reply_text(ABOUT_TEXT)
    except TelegramError as err:
        logger.warning("Could not reply to /about: %s", type(err).__name__)


# ---------------------------------------------------------------------------
# Automatic 10-minute broadcast loop (runs inside this same process)
# ---------------------------------------------------------------------------
async def _send_to_subscriber(app: Application, chat_id: int, text: str) -> None:
    """Send one message and handle blocked users / rate limits."""
    try:
        await app.bot.send_message(chat_id=chat_id, text=text)
    except RetryAfter as err:
        # Telegram asked us to slow down. Wait the requested time and retry once.
        wait_seconds = int(getattr(err, "retry_after", 5)) + 1
        logger.warning("Rate limit hit. Waiting %d seconds before retry.",
                       wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Forbidden:
            subscribers.discard(chat_id)
            logger.info("Subscriber blocked the bot (during retry); removed.")
        except TelegramError as retry_err:
            logger.warning("Retry failed for one subscriber: %s",
                           type(retry_err).__name__)
    except Forbidden:
        # User blocked the bot or deleted the chat — drop them.
        subscribers.discard(chat_id)
        logger.info("Subscriber blocked the bot; removed from list.")
    except TelegramError as err:
        # Any other Telegram-side problem: log and move on, never crash.
        logger.warning("Failed to send to one subscriber: %s",
                       type(err).__name__)
    except Exception as err:  # network hiccups etc.
        logger.warning("Unexpected send error: %s", type(err).__name__)


async def broadcast_once(app: Application, item: dict) -> None:
    """Send one content item to every active subscriber."""
    text = format_item(item)

    # Defence in depth: re-check right before sending.
    if not is_content_safe(text):
        logger.warning("Broadcast skipped: content failed safety check.")
        return

    if not subscribers:
        logger.info("Broadcast tick: no active subscribers.")
        return

    targets = list(subscribers)  # copy, because the set may change mid-loop
    logger.info("Broadcast tick: sending to %d subscriber(s).", len(targets))

    for chat_id in targets:
        await _send_to_subscriber(app, chat_id, text)
        # Small pacing to stay well below Telegram's rate limits.
        await asyncio.sleep(SEND_PACING_SECONDS)


async def broadcast_loop(app: Application) -> None:
    """Send an update to all subscribers every UPDATE_INTERVAL_SECONDS."""
    index = 0
    pool_size = len(SAFE_CONTENT)

    if pool_size == 0:
        logger.error("No safe content items available. Broadcast loop is idle.")
        return

    while True:
        try:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            item = SAFE_CONTENT[index % pool_size]
            index += 1
            await broadcast_once(app, item)
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled.")
            raise
        except Exception as err:
            # Never let the loop die from a single failure.
            logger.exception("Broadcast loop error: %s", type(err).__name__)


# Keep a reference so the task is not garbage-collected.
_background_tasks: set[asyncio.Task] = set()


async def post_init(app: Application) -> None:
    """Start the background broadcast loop once the app is ready."""
    task = asyncio.create_task(broadcast_loop(app), name="broadcast_loop")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("Broadcast loop started (every %d seconds).",
                UPDATE_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # BOT_TOKEN is read here from the environment.
    # On Railway this variable is set in Project → Variables.
    if not BOT_TOKEN:
        logger.error(
            "BOT_TOKEN environment variable is missing. "
            "Set it in Railway → Variables and redeploy. "
            "The application will now stop."
        )
        raise SystemExit(1)

    logger.info("Starting Starz Promosyon bot (long polling)…")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))

    # Long polling — no public webhook URL required.
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
