import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from pymongo.collection import Collection
import aiohttp
import logging
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from os import environ
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configure logging with more detail
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot configuration from os.environ
API_ID = int(environ.get('API_ID',"12618934"))
API_HASH = environ.get('API_HASH',"49aacd0bc2f8924add29fb02e20c8a16")
try:
    BOT_TOKEN = environ.get('BOT_TOKEN',"7854832338:AAGmEzyYImK80tW5Ll0MaAzW52usqxEzcuU")
    MONGO_URI = environ.get('MONGO_URI',"mongodb+srv://pcmovies:pcmovies@cluster0.4vv9ebl.mongodb.net/?retryWrites=true&w=majority")
    CHANNEL_USERNAME = "@moviegroupbat"  # Change this
    ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "5032034594").split(",")))
except KeyError as e:
 logger.error(f"Missing required environment variable: {e}")
 raise ValueError(f"Environment variable {e} is not set.")

 # Log all environment variables for debugging
logger.debug("All environment variables: %s", os.environ)
logger.info(f"Loaded API_ID: {API_ID}")
logger.info(f"Loaded API_HASH: {API_HASH}")
logger.info(f"Loaded BOT_TOKEN: {BOT_TOKEN}")
logger.info(f"Loaded MONGO_URI: {MONGO_URI}")
logger.info(f"Loaded ADMIN_IDS: {ADMIN_IDS}")

# Validate critical variables
if not MONGO_URI or MONGO_URI.strip() == "":
 raise ValueError("MONGO_URI is empty. Please provide a valid MongoDB connection string.")
if not API_ID or not API_HASH or not BOT_TOKEN:
 raise ValueError("API_ID, API_HASH, or BOT_TOKEN is empty. Please provide valid Telegram API credentials.")

# Simple HTTP server for Koyeb health check
class HealthCheckHandler(BaseHTTPRequestHandler):
def do_GET(self):
 self.send_response(200)
 self.send_header("Content-type", "text/plain")
 self.end_headers()
 self.wfile.write(b"OK")
 logger.debug("Health check responded with OK")

def start_health_server():
 port = int(os.environ.get("PORT", 8000)) # Use Koyeb's PORT env var
 server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
 logger.info(f"Starting health check server on port {port}")
 server.serve_forever()

# Initialize Pyrogram client
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, workers=50)
mongo_client = MongoClient(MONGO_URI, maxPoolSize=50)
db = mongo_client["movie_db"]
movies_collection = db["movies"]

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
 logger.debug(f"Subscription check for user {user_id}: {member.status}")
 return member.status in ["member", "administrator", "creator"]
 except Exception as e:
 logger.error(f"Subscription check failed for user {user_id}: {e}")
 return False

# Raw update handler for all messages
@app.on_raw_update()
async def raw_update(client, update, users, chats):
 logger.debug(f"Raw update received: {update}")

# Greeting message for users (text only)
@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
 user_id = message.from_user.id
 logger.info(f"Received /start from user_id: {user_id}")
 is_admin = user_id in ADMIN_IDS

 try:
 if not await check_subscription(user_id):
 logger.info(f"User {user_id} not subscribed to {CHANNEL_USERNAME}")
 await message.reply(
 "Please join our channel first!\n"
 f"Join here: https://t.me/{CHANNEL_USERNAME[1:]}",
 reply_markup=InlineKeyboardMarkup([
 [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
 [InlineKeyboardButton("Try Again", callback_data="check_sub")]
 ])
 )
 return
 
 if is_admin:
 logger.info(f"Admin {user_id} started bot")
 await message.reply(
 "🎬 Welcome, Admin! 🍿\n"
 "Fastest Movie Bot at your service!\n"
 "• Type a movie name to request\n"
 "• Forward a movie file to add it"
 )
 else:
 logger.info(f"User {user_id} started bot")
 await message.reply(
 "🎬 Welcome to Movie Bot! 🍿\n"
 "Fastest way to get your favorite movies!\n"
 "• Type a movie name to request"
 )
 except Exception as e:
 logger.error(f"Error in start handler for user {user_id}: {e}")
 await message.reply("An error occurred. Please try again later.")

# Handle subscription check
@app.on_callback_query(filters.regex("check_sub"))
async def check_sub_callback(client, callback):
 user_id = callback.from_user.id
 logger.info(f"Received check_sub callback from user_id: {user_id}")
 try:
 if await check_subscription(user_id):
 await callback.message.delete()
 await start(client, callback.message)
 else:
 await callback.answer("Please join the channel first!", show_alert=True)
 except Exception as e:
 logger.error(f"Error in check_sub callback for user {user_id}: {e}")
 await callback.answer("An error occurred. Please try again.")

# Handle movie requests ( text only)
@app.on_message(filters.text & filters.private)
async def handle_movie_request(client, message):
 user_id = message.from_user.id
 
 try:
 if not await check_subscription(user_id):
 await message.reply(
 "Please join our channel first!\n"
 f"Join here: https://t.me/{CHANNEL_USERNAME[1:]}",
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
 except Exception as e:
 logger.error(f"Error in handle_movie_request for user {user_id}: {e}")
 await message.reply("An error occurred while processing your request.")

# Handle forwarded movie files - Admin only (text only)
@app.on_message(filters.document & filters.private)
async def handle_movie_upload(client, message):
 user_id = message.from_user.id
 
 try:
 if not await check_subscription(user_id):
 await message.reply(
 "Please join our channel first!\n"
 f"Join here: https://t.me/{CHANNEL_USERNAME[1:]}",
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
 except Exception as e:
 logger.error(f"Error in handle_movie_upload for user {user_id}: {e}")
 await message.reply("An error occurred while indexing the movie.")

# Upload progress callback
async def upload_progress(current, total, message):
 if current == total:
 return
 if current % (total // 4) == 0:
 await message.edit_text(f"Uploading: {int((current/total)*100)}%")

# Optimize MongoDB
async def setup_database():
 logger.info("Setting up database indexes...")
 try:
 await asyncio.get_running_loop().run_in_executor(
 executor, lambda: movies_collection.create_index([("title", "text")])
 )
 await asyncio.get_running_loop().run_in_executor(
 executor, lambda: movies_collection.create_index([("title", 1)], unique=True)
 )
 logger.info("Database indexes created successfully.")
 except Exception as e:
 logger.error(f"Error setting up database indexes: {e}")

if __name__ == "__main__":
 # Start health check server in a separate thread
 threading.Thread(target=start_health_server, daemon=True).start()
 loop = asyncio.get_event_loop()
 loop.run_until_complete(setup_database())
 logger.info("Bot starting...")
 app.run()