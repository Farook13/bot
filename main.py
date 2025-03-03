import os
import asyncio
import threading
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
import aiohttp
import logging
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration
try:
    API_ID = int(os.environ.get('API_ID', '12618934'))
    API_HASH = os.environ.get('API_HASH', '49aacd0bc2f8924add29fb02e20c8a16')
    BOT_TOKEN = os.environ.get('BOT_TOKEN', '7854832338:AAGmEzyYImK80tW5Ll0MaAzW52usqxEzcuU')
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://pcmovies:pcmovies@cluster0.4vv9ebl.mongodb.net/?retryWrites=true&w=majority')
    CHANNEL_USERNAME = '@moviegroupbat'
    ADMIN_IDS = set(map(int, os.environ.get('ADMIN_IDS', '5032034594').split(',')))
except (ValueError, TypeError) as e:
    logger.error(f"Invalid configuration: {e}")
    raise

logger.info("Configuration loaded successfully")

# Health check server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
        logger.debug("Health check OK")

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server starting on port {port}")
    server.serve_forever()

# Initialize clients
try:
    app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50)
    mongo_client = MongoClient(MONGO_URI, maxPoolSize=50)
    db = mongo_client["movie_db"]
    movies_collection = db["movies"]
    executor = ThreadPoolExecutor(max_workers=10)
    logger.info("Clients initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize clients: {e}")
    raise

# Test MongoDB connection
try:
    mongo_client.server_info()
    logger.info("MongoDB connection successful")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    raise

# IMDB cache
@lru_cache(maxsize=1000)
async def get_imdb_info(movie_name):
    async with aiohttp.ClientSession() as session:
        url = f"http://www.omdbapi.com/?t={movie_name}&apikey=your_omdb_api_key"
        try:
            async with session.get(url) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"IMDB API error for {movie_name}: {e}")
            return {}

async def check_subscription(user_id):
    try:
        member = await app.get_chat_member(CHANNEL_USERNAME, user_id)
        status = member.status in ["member", "administrator", "creator"]
        logger.debug(f"Subscription check for {user_id}: {status}")
        return status
    except Exception as e:
        logger.error(f"Subscription check failed for {user_id}: {e}")
        return False

@app.on_raw_update()
async def raw_update(client, update, users, chats):
    logger.debug(f"Raw update received: {update}")

@app.on_message()
async def catch_all(client, message):
    logger.info(f"Received message from {message.from_user.id}: {message.text or 'No text'}")

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    logger.info(f"Received /start from user {user_id}")
    is_admin = user_id in ADMIN_IDS
    
    subscribed = await check_subscription(user_id)
    logger.info(f"Subscription check for {user_id}: {subscribed}")
    
    if not subscribed:
        logger.info(f"User {user_id} not subscribed to {CHANNEL_USERNAME}")
        await message.reply(
            f"Please join our channel first!\nJoin: https://t.me/{CHANNEL_USERNAME[1:]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return

    welcome_msg = (
        "🎬 Welcome, Admin! 🍿\nFastest Movie Bot at your service!\n"
        "• Type a movie name to request\n• Forward a movie file to add it"
    ) if is_admin else (
        "🎬 Welcome to Movie Bot! 🍿\nFastest way to get your favorite movies!\n"
        "• Type a movie name to request"
    )
    logger.info(f"Sending welcome message to {user_id}")
    await message.reply(welcome_msg)

@app.on_callback_query(filters.regex("check_sub"))
async def check_sub_callback(client, callback):
    user_id = callback.from_user.id
    logger.info(f"Received check_sub callback from {user_id}")
    
    subscribed = await check_subscription(user_id)
    logger.info(f"Subscription check for {user_id}: {subscribed}")
    
    if subscribed:
        await callback.message.delete()
        await start(client, callback.message)
    else:
        await callback.answer("Please join the channel first!", show_alert=True)

@app.on_message(filters.text & filters.private)
async def handle_movie_request(client, message):
    user_id = message.from_user.id
    logger.info(f"Received movie request from {user_id}: {message.text}")
    
    subscribed = await check_subscription(user_id)
    logger.info(f"Subscription check for {user_id}: {subscribed}")
    
    if not subscribed:
        await message.reply(
            f"Please join our channel first!\nJoin: https://t.me/{CHANNEL_USERNAME[1:]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return

    movie_name = message.text.strip()
    logger.info(f"Searching for movie: {movie_name}")
    movie_data = await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.find_one, {"title": {"$regex": movie_name, "$options": "i"}}
    )
    
    if not movie_data:
        logger.info(f"Movie not found: {movie_name}")
        await message.reply("Movie not found! Contact an admin to add it.")
        return

    imdb_info = await get_imdb_info(movie_name)
    caption = (
        f"🎬 {movie_data['title']}\n"
        f"⭐ IMDB: {imdb_info.get('imdbRating', 'N/A')}\n"
        f"📜 {imdb_info.get('Plot', 'No description available')}"
    )
    logger.info(f"Sending movie {movie_data['title']} to {user_id}")
    await message.reply_document(
        document=movie_data["file_id"],
        caption=caption,
        quote=True,
        progress=upload_progress,
        progress_args=(message,)
    )

@app.on_message(filters.document & filters.private)
async def handle_movie_upload(client, message):
    user_id = message.from_user.id
    logger.info(f"Received document from {user_id}")
    
    subscribed = await check_subscription(user_id)
    logger.info(f"Subscription check for {user_id}: {subscribed}")
    
    if not subscribed:
        await message.reply(
            f"Please join our channel first!\nJoin: https://t.me/{CHANNEL_USERNAME[1:]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Try Again", callback_data="check_sub")]
            ])
        )
        return

    if user_id not in ADMIN_IDS:
        logger.info(f"Non-admin {user_id} tried to upload")
        await message.reply("Sorry, only admins can add movies!")
        return

    if not message.document.mime_type.startswith("video/"):
        logger.info(f"Invalid file type from {user_id}")
        await message.reply("Please forward a video file!")
        return

    file_id = message.document.file_id
    movie_title = os.path.splitext(message.document.file_name or "Untitled")[0].strip()
    
    exists = await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.count_documents, {"title": movie_title}
    )
    
    if exists:
        logger.info(f"Movie {movie_title} already exists")
        await message.reply(f"'{movie_title}' is already in the database!")
        return

    movie_data = {"title": movie_title, "file_id": file_id}
    await asyncio.get_running_loop().run_in_executor(
        executor, movies_collection.insert_one, movie_data
    )
    logger.info(f"Movie {movie_title} indexed successfully")
    await message.reply(f"✅ '{movie_title}' indexed successfully!")

async def upload_progress(current, total, message):
    if current == total or current % (total // 4) == 0:
        percentage = int((current/total)*100)
        await message.edit_text(f"Uploading: {percentage}%")

async def setup_database():
    try:
        await asyncio.get_running_loop().run_in_executor(
            executor, lambda: movies_collection.create_index([("title", "text")])
        )
        await asyncio.get_running_loop().run_in_executor(
            executor, lambda: movies_collection.create_index([("title", 1)], unique=True)
        )
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Database setup failed: {e}")

async def main():
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    try:
        await setup_database()
        await app.start()
        # Get and log bot info to confirm identity
        me = await app.get_me()
        logger.info(f"Bot started as @{me.username} (ID: {me.id})")
        logger.info("Bot is running...")
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Main loop failed: {e}")
    finally:
        await app.stop()
        mongo_client.close()
        logger.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Application failed to start: {e}")