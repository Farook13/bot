import os
import asyncio
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

# Validate configuration
if not all([API_ID, API_HASH, BOT_TOKEN, MONGO_URI]):
    raise ValueError("Required configuration parameters are missing")

# Health check server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server running on port {port}")
    server.serve_forever()

# Initialize clients
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50)
mongo_client = MongoClient(MONGO_URI, maxPoolSize=50)
db = mongo_client["movie_db"]
movies_collection = db["movies"]
executor = ThreadPoolExecutor(max_workers=10)

# IMDB cache
@lru_cache(maxsize=1000)
async def get_imdb_info(movie_name):
    async with aiohttp.ClientSession() as session:
        url = f"http://www.omdbapi.com/?t={movie_name}&apikey=your_omdb_api_key"
        try:
            async with session.get(url) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"IMDB API error: {e}")
            return {}

async def check_subscription(user_id):
    try:
        member = await app.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Subscription check failed for {user_id}: {e}")
        return False

@app.on_raw_update()
async def raw_update(client, update, users, chats):
    logger.debug(f"Raw update: {update}")

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    if not await check_subscription(user_id):
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
    await message.reply(welcome_msg)

@app.on_callback_query(filters.regex("check_sub"))
async def check_sub_callback(client, callback):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        await callback.message.delete()
        await start(client, callback.message)
    else:
        await callback.answer("Please join the channel first!", show_alert=True)

@app.on_message(filters.text & filters.private)
async def handle_movie_request(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply(
            f"Please join our channel first!\nJoin: https://t.me/{CHANNEL_USERNAME[1:]}",
            reply_markup=InlineKeyboardMarkup([
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

@app.on_message(filters.document & filters.private)
async def handle_movie_upload(client, message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.reply(
            f"Please join our channel first!\nJoin: https://t.me/{CHANNEL_USERNAME[1:]}",
            reply_markup=InlineKeyboardMarkup([
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
    movie_title = os.path.splitext(message.document.file_name or "Untitled")[0].strip()
    
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
    threading.Thread(target=start_health_server, daemon=True).start()
    await setup_database()
    await app.start()
    logger.info("Bot is running...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())