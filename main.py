# To run: python -m hypercorn main.py:app --bind 0.0.0.0:5000

import asyncio
import json
import os
import random
import time
from threading import Thread
from quart import Quart, jsonify, request
from redis.asyncio import Redis
from twscrape import API, gather
from twscrape.logger import set_log_level
from dotenv import load_dotenv
import aiohttp

load_dotenv()

app = Quart(__name__)

# Load proxies from proxies.json
with open('proxies.json') as f:
    proxies_data = json.load(f)
PROXIES = proxies_data["proxies"]

API_URLS = [
    "https://cobalt-us.schizo.city/api/json",
    "https://cobalt-fi.schizo.city/api/json",
    "https://capi.tieren.men/api/json",
    "http://193.123.56.138:9000/api/json/",
    "http://152.67.111.114:9000/api/json/"
]

HEADERS = {
    "Accept": "application/json",
}

redis_url = "redis://default:JXBiJVVnCPayxeYtCtvCQGrhEzIfkxrm@monorail.proxy.rlwy.net:51062"
redis = Redis.from_url(redis_url)

request_queue = asyncio.Queue()

def get_api():
    db_path = "accounts.db"
    api = API(db_path if os.path.exists(db_path) else None)
    

    async def add_account():
        if not os.path.exists(db_path):

    asyncio.create_task(add_account())

    set_log_level("DEBUG")
    return api

async def fetch_media_content(session, tweet_url):
    proxy_url = random.choice(PROXIES)
    api_url = random.choice(API_URLS)

    payload = {
        "url": tweet_url,
        "vQuality": "1080"
    }
    
    try:
        proxy_api_url = f"{proxy_url}?destination={api_url}"
        async with session.post(proxy_api_url, json=payload, headers=HEADERS, timeout=5) as response:
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
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
        print(f"Connection error or timeout: {e}")
        return []

async def fetch_user_data(user_login, tweet_count):
    # Check Redis cache first
    cache_key = f"user:{user_login}:{tweet_count}"
    cached_data = await redis.get(cache_key)
    if cached_data:
        print(f"Cache hit for {user_login} with {tweet_count} tweets")
        return json.loads(cached_data)

    api = get_api()
    user = await api.user_by_login(user_login)
    user_id = user.id

    tweets = await gather(api.user_tweets(user_id, limit=tweet_count))

    connector = aiohttp.TCPConnector(limit=100, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_media_content(session, tweet.url) for tweet in tweets]
        media_contents = await asyncio.gather(*tasks)

    tweet_data = [
        {
            "tweet_url": tweet.url,
            "tweet_text": tweet.rawContent,
            "media_content": media_content
        }
        for tweet, media_content in zip(tweets, media_contents)
    ]

    user_data = {
        "user_info": user.dict(),
        "tweets": tweet_data,
    }

    # Store result in Redis cache
    await redis.set(cache_key, json.dumps(user_data, default=str), ex=3600)

    return user_data

async def process_request_queue():
    while True:
        user_login, tweet_count = await request_queue.get()
        try:
            await fetch_user_data(user_login, tweet_count)
        except Exception as e:
            print(f"Error processing request for {user_login}: {e}")
        request_queue.task_done()

@app.route("/user/<string:user_login>", methods=["GET"])
async def get_user_data_route(user_login):
    tweet_count = request.args.get("data", default=10, type=int)

    # Start timing
    start_time = time.time()

    await request_queue.put((user_login, tweet_count))
    user_data = await fetch_user_data(user_login, tweet_count)

    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    print(f"Request for {user_login} with {tweet_count} tweets took {elapsed_time:.2f} seconds")

    return jsonify(user_data)

async def background_caching():
    # Load most requested users from JSON file
    with open('most_requested_users.json') as f:
        most_requested_users_data = json.load(f)
    
    # Extract user logins from URLs
    most_requested_users = [
        url.split("/")[-1] for url in most_requested_users_data["users"]
    ]
    
    tweet_count = 10
    
    while True:
        for user_login in most_requested_users:
            await request_queue.put((user_login, tweet_count))
            await request_queue.join()
        
        tweet_count += 1
        if tweet_count > 50:  # This sets the maximum number of tweets to cache
            tweet_count = 10  # Reset to 10 and start the process again
        
        await asyncio.sleep(3600)  # Sleep for an hour before the next caching round

def run_background_caching():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(background_caching())

if __name__ == "__main__":
    # Start background caching in a separate thread
    background_thread = Thread(target=run_background_caching)
    background_thread.start()

    # Start processing the request queue in the main event loop
    asyncio.run(process_request_queue())

    app.run(host="0.0.0.0", debug=True)
