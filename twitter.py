from quart import jsonify, request
import asyncio
import os
from twscrape import API, gather
from twscrape.logger import set_log_level
from dotenv import load_dotenv
from functools import lru_cache
import orjson
import random
import time
import aiohttp
from aiohttp_retry import RetryClient, ExponentialRetry
import redis.asyncio as aioredis
import redis.exceptions

load_dotenv()

# Redis setup
redis_url = "redis://default:JXBiJVVnCPayxeYtCtvCQGrhEzIfkxrm@monorail.proxy.rlwy.net:51062"
redis_conn = aioredis.from_url(redis_url, decode_responses=True)

API_URLS = [
    "https://cobalt-us.schizo.city/api/json",
    "https://cobalt-fi.schizo.city/api/json",
    "https://capi.tieren.men/api/json",
    "http://193.123.56.138:9000/api/json/",
    "http://152.67.111.114:9000/api/json/"
]

with open('proxy_urls.json', 'r') as f:
    PROXY_URLS = orjson.loads(f.read())['proxies']

HEADERS = {
    "Accept": "application/json",
}

@lru_cache(maxsize=32)
def get_api():
    db_path = "accounts.db"
    api = API(db_path if os.path.exists(db_path) else None)
    
    set_log_level("DEBUG")
    return api

def get_proxy_and_api_url():
    proxy = random.choice(PROXY_URLS)
    api_url = random.choice(API_URLS)
    return proxy, api_url

async def fetch_media_content(session, tweet_url):
    cached_media = await redis_conn.get(tweet_url)
    if cached_media:
        return orjson.loads(cached_media)

    payload = {
        "url": tweet_url,
        "vQuality": "1080"
    }
    
    proxy_url, api_url = get_proxy_and_api_url()
    full_url = f"{proxy_url}?destination={api_url}"
    
    async with session.post(full_url, json=payload, headers=HEADERS) as response:
        if response.status == 200:
            response_data = await response.json(loads=orjson.loads)
            if response_data.get("status") == "redirect":
                media_content = [response_data.get("url")]
            elif response_data.get("status") == "error":
                print(f"Error fetching media: {response_data.get('text')}")
                media_content = []
            else:
                media_content = response_data.get("media", [])
            
            await redis_conn.setex(tweet_url, 300, orjson.dumps(media_content))
            return media_content
        return []

async def fetch_user_and_tweets(user_login, tweet_count):
    api = get_api()
    user = await api.user_by_login(user_login)
    tweets = await gather(api.user_tweets(user.id, limit=tweet_count))
    return user, tweets

async def fetch_user_data(user_login, tweet_count):
    cache_key = f"{user_login}_{tweet_count}"
    cached_user_data = await redis_conn.get(cache_key)
    if cached_user_data:
        return orjson.loads(cached_user_data)

    user, tweets = await fetch_user_and_tweets(user_login, tweet_count)

    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300, use_dns_cache=True)
    retry_options = ExponentialRetry(attempts=3)
    async with RetryClient(connector=connector, retry_options=retry_options) as session:
        tasks = [fetch_media_content(session, tweet.url) for tweet in tweets]
        media_contents = await asyncio.gather(*tasks)

    tweet_data = [
        {
            "tweet_url": tweet.url,
            "tweet_text": tweet.rawContent.replace('\n', ' '),
            "media_content": media_content
        }
        for tweet, media_content in zip(tweets, media_contents)
    ]
        
    user_data = {
        "user_info": user.dict(),
        "tweets": tweet_data,
    }

    await redis_conn.setex(cache_key, 300, orjson.dumps(user_data))
    return user_data


async def get_user_data_route(user_login):
    start_time = time.time()
    tweet_count = request.args.get("data", default=10, type=int)
    
    user_data = await fetch_user_data(user_login, tweet_count)

    # Return initial data immediately and continue fetching more tweets in the background
    asyncio.create_task(fetch_user_data(user_login, tweet_count + 10))
    
    end_time = time.time()
    print(f"Request processed in {end_time - start_time:.2f} seconds")
    return jsonify(user_data)

async def preflight_cache():
    with open("most_requested_users.json", "r") as f:
        users = orjson.loads(f.read())["users"]
    
    last_processed_index = 0
    
    while True:
        for i in range(last_processed_index, len(users)):
            user_url = users[i]
            user_login = user_url.split("/")[-1]
            cache_key = f"{user_login}_10"
            try:
                if not await redis_conn.exists(cache_key):
                    print(f"Pre-caching data for {user_login}")
                    await fetch_user_data(user_login, 10)
                last_processed_index = i + 1
            except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
                print(f"Redis connection error: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)
                continue
        
        # Reset index after completing the loop
        last_processed_index = 0
        await asyncio.sleep(300)  # Sleep for 5 minutes before re-caching
