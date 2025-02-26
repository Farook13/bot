import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from pymongo.collection import Collection
import aiohttp
import logging
from functools import lru_cache
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.getenv("12618934")
API_HASH = os.getenv("49aacd0bc2f8924add29fb02e20c8a16")
BOT_TOKEN = os.getenv("7857321740:AAHSUfjwO3w6Uffmxm9vCUMl36FtXl5-r6w")
MONGO_URI = os.getenv("mongo dp not found")
CHANNEL_USERNAME = "@moviegroupbat"  # Change this
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "5032034594").split(",")))  # Comma-separated admin Telegram IDs


# Log and validate MONGO_URI
logger.info(f"Loaded MONGO_URI: {MONGO_URI}")
if not MONGO_URI or MONGO_URI.strip() == "":
    raise ValueError("MONGO_URI environment variable is not set or is empty. Please provide a valid MongoDB connection string.")

# Initialize clients with optimization
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50)
mongo_client = MongoClient(MONGO_URI, maxPoolSize=50)
db = mongo_client["movie_db"]
movies_collection: Collection = db["movies"]

# Thread pool for database operations
executor = ThreadPoolExecutor(max_workers=10)

# Cache for IMDB data
@lru_cache(maxsize=1000)
async def get_imdb_info(movie_name):
    async with aiohttp.ClientSession() as session:
        url = f"http://www.omdbapi.com/?t={movie_name}&apikey=your_omdb_api_key"
        async with session.get(url) as response:
            return await response.json()

# Check subscription status
async def check_subscription(user_id):
    try:
        member = await app.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# Greeting message for users
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    if not await check_subscription(user_id):
        await message.reply_photo(
            photo="not_subscribed.jpg",
            caption="Please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return
    
    if is_admin:
        await message.reply_photo(
            photo="admin_welcome.jpg",
            caption=(
                "🎬 Welcome, Admin! 🍿\n"
                "Fastest Movie Bot at your service!\n"
                "• Type a movie name to request\n"
                "• Forward a movie file to add it"
            )
        )
    else:
        await message.reply_photo(
            photo="user_welcome.jpg",
            caption=(
                "🎬 Welcome to Movie Bot! 🍿\n"
                "Fastest way to get your favorite movies!\n"
                "• Type a movie name to request"
            )
        )

# Handle subscription check
@app.on_callback_query(filters.regex("check_sub"))
async def check_sub_callback(client, callback):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        await start(client, callback.message)
    else:
        await callback.answer("Please join the channel first!", show_alert=True)

# Handle movie requests
@app.on_message(filters.text & filters.private)
async def handle_movie_request(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply_photo(
            photo="not_subscribed.jpg",
            caption="Please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return
    
    movie_name = message.text.strip()
    movie_data = await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.find_one, {"title": {"$regex": movie_name, "$options": "i"}}
    )
    
    if not movie_data:
        await message.reply("Movie not found! Contact an admin to add it.")
        return
    
    imdb_info = await get_imdb_info(movie_name)
    caption = (
        f"🎬 {movie_data['title']}\n"
        f"⭐ IMDB: {imdb_info.get('imdbRating', 'N/A')}\n"
        f"📜 {imdb_info.get('Plot', 'No description available')}"
    )
    
    await message.reply_document(
        document=movie_data["file_id"],
        caption=caption,
        quote=True,
        progress=upload_progress,
        progress_args=(message,)
    )

# Handle forwarded movie files - Admin only
@app.on_message(filters.document & filters.private)
async def handle_movie_upload(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply_photo(
            photo="not_subscribed.jpg",
            caption="Please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return
    
    if user_id not in ADMIN_IDS:
        await message.reply("Sorry, only admins can add movies!")
        return
    
    if not message.document.mime_type.startswith("video/"):
        await message.reply("Please forward a video file!")
        return
    
    file_id = message.document.file_id
    file_name = message.document.file_name or "Untitled"
    
    movie_title = os.path.splitext(file_name)[0].strip()
    
    exists = await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.count_documents, {"title": movie_title}
    )
    
    if exists:
        await message.reply(f"'{movie_title}' is already in the database!")
        return
    
    movie_data = {"title": movie_title, "file_id": file_id}
    await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.insert_one, movie_data
    )
    
    await message.reply(f"✅ '{movie_title}' indexed successfully!")

# Upload progress callback
async def upload_progress(current, total, message):
    if current == total:
        return
    if current % (total // 4) == 0:
        await message.edit_text(f"Uploading: {int((current/total)*100)}%")

# Optimize MongoDB
async def setup_database():
    await asyncio.get_running_loop().run_in_executor(
        executor, lambda: movies_collection.create_index([("title", "text")])
    )
    await asyncio.get_running_loop().run_in_executor(
        executor, lambda: movies_collection.create_index([("title", 1)], unique=True)
    )

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_database())
    logger.info("Bot starting...")
    app.run()
