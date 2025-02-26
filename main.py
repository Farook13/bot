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

# Bot configuration
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_USERNAME = "@YourChannelUsername"  # Change this

# Initialize clients with optimization
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50)  # Increased workers
mongo_client = MongoClient(MONGO_URI, maxPoolSize=50)  # Connection pooling
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

# Check subscription status (cached internally by Pyrogram)
async def check_subscription(user_id):
    try:
        member = await app.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# Greeting message
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.reply(
            "Please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return
    
    welcome_msg = (
        "🎬 Welcome to Movie Bot! 🍿\n"
        "Fastest way to get your favorite movies!\n"
        "• Type a movie name to request\n"
        "• Forward a movie file to add it"
    )
    await message.reply(welcome_msg)

# Handle subscription check
@app.on_callback_query(filters.regex("check_sub"))
async def check_sub_callback(client, callback):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.edit("✅ Subscription verified! Type a movie name or forward a file!")
    else:
        await callback.answer("Please join the channel first!", show_alert=True)

# Handle movie requests (text input)
@app.on_message(filters.text & filters.private)
async def handle_movie_request(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply(
            "Please join our channel first!",
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
        await message.reply("Movie not found! Try forwarding the movie file to add it.")
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

# Handle forwarded movie files with faster indexing
@app.on_message(filters.document & filters.private)
async def handle_movie_upload(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply(
            "Please join our channel first!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return
    
    if not message.document.mime_type.startswith("video/"):
        await message.reply("Please forward a video file!")
        return
    
    file_id = message.document.file_id
    file_name = message.document.file_name or "Untitled"  # Fallback for missing filename
    
    # Extract movie title (remove extension, trim efficiently)
    movie_title = os.path.splitext(file_name)[0].strip()
    
    # Fast existence check using count_documents (more efficient than find_one for this purpose)
    exists = await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.count_documents, {"title": movie_title}
    )
    
    if exists:
        await message.reply(f"'{movie_title}' is already in the database!")
        return
    
    # Prepare movie data
    movie_data = {"title": movie_title, "file_id": file_id}
    
    # Batch insert in thread pool (minimal overhead)
    await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.insert_one, movie_data
    )
    
    await message.reply(f"✅ '{movie_title}' indexed successfully!")

# Upload progress callback (optimized)
async def upload_progress(current, total, message):
    if current == total:
        return
    # Reduce updates to every 25% for less overhead
    if current % (total // 4) == 0:
        await message.edit_text(f"Uploading: {int((current/total)*100)}%")

# Optimize MongoDB
async def setup_database():
    # Ensure indexes exist (run once)
    await asyncio.get_running_loop().run_in_executor(
        executor, lambda: movies_collection.create_index([("title", "text")])
    )
    # Unique index on title for faster duplicate checks
    await asyncio.get_running_loop().run_in_executor(
        executor, lambda: movies_collection.create_index([("title", 1)], unique=True)
    )

if name == "__main__":
    # Start bot
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_database())
    logger.info("Bot starting...")
    app.run()
​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​​
