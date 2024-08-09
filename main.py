# To run: python -m hypercorn main.py:app --bind 0.0.0.0:5000
from flask import Flask, jsonify, request
import asyncio
import os
import aiohttp
from twscrape import API, gather
from twscrape.logger import set_log_level
from dotenv import load_dotenv
from threading import Timer
from cachetools import TTLCache
from functools import lru_cache

load_dotenv()

app = Flask(__name__)

API_URLS = [
    "https://cobalt-us.schizo.city/api/json",
    "https://cobalt-fi.schizo.city/api/json",
    "https://capi.tieren.men/api/json",
    "http://193.123.56.138:9000/api/json/",
    "http://152.67.111.114:9000/api/json/"
]

current_api_index = 0

def switch_api_url():
    global current_api_index
    current_api_index = (current_api_index + 1) % len(API_URLS)
    Timer(600, switch_api_url).start()  # Switch every 600 seconds (10 minutes)

switch_api_url()

HEADERS = {
    "Accept": "application/json",
}

# Create a cache with a 5-minute TTL
cache = TTLCache(maxsize=100, ttl=300)

@lru_cache(maxsize=32)
def get_api():
    db_path = "accounts.db"
    api = API(db_path if os.path.exists(db_path) else None)
    

    async def add_account():
        if not os.path.exists(db_path):

    asyncio.create_task(add_account())

    set_log_level("DEBUG")
    return api

async def fetch_media_content(session, tweet_url):
    payload = {
        "url": tweet_url,
        "vQuality": "1080"
    }
    
    try:
        async with session.post(API_URLS[current_api_index], json=payload, headers=HEADERS) as response:
            if response.status == 200:
                response_data = await response.json()
                if response_data.get("status") == "redirect":
                    return [response_data.get("url")]
                elif response_data.get("status") == "error":
                    print(f"Error fetching media: {response_data.get('text')}")
                    return []
                else:
                    return response_data.get("media", [])
            return []
    except aiohttp.ClientConnectorError as e:
        print(f"Connection error: {e}")
        return []

async def fetch_user_data(user_login, tweet_count):
    cache_key = f"{user_login}_{tweet_count}"
    if cache_key in cache:
        return cache[cache_key]

    api = get_api()
    
    user = await api.user_by_login(user_login)
    user_id = user.id

    # Fetch user tweets
    tweets = await gather(api.user_tweets(user_id, limit=tweet_count))

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_media_content(session, tweet.url) for tweet in tweets]
        media_contents = await asyncio.gather(*tasks)

    tweet_data = []
    for tweet, media_content in zip(tweets, media_contents):
        tweet_info = {
            "tweet_url": tweet.url,
            "tweet_text": tweet.rawContent,
            "media_content": media_content
        }
        tweet_data.append(tweet_info)
        
    user_data = {
        "user_info": user.dict(),
        "tweets": tweet_data,
    }

    cache[cache_key] = user_data
    return user_data

@app.route("/user/<string:user_login>", methods=["GET"])
async def get_user_data(user_login):
    tweet_count = request.args.get("data", default=10, type=int)
    user_data = await fetch_user_data(user_login, tweet_count)
    return jsonify(user_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)