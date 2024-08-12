import aiohttp
from bs4 import BeautifulSoup
from quart import Blueprint, jsonify, request
from redis.asyncio import Redis
import asyncio
import json
import os

# Define the Coomer-specific app
com_app = Blueprint('com', __name__)

# Redis setup
redis_url = "redis://default:JXBiJVVnCPayxeYtCtvCQGrhEzIfkxrm@monorail.proxy.rlwy.net:51062"
redis = Redis.from_url(redis_url)

session = None

async def get_session():
    global session
    if session is None:
        connector = aiohttp.TCPConnector(limit=100, force_close=True)
        session = aiohttp.ClientSession(connector=connector)
    return session

async def fetch_page(url, retries=3):
    for attempt in range(retries):
        try:
            session = await get_session()
            async with session.get(url, timeout=10) as response:
                if response.status == 429:
                    # Rate limit error, raise an exception
                    raise aiohttp.ClientResponseError(
                        status=response.status, message="Rate limit exceeded"
                    )
                response.raise_for_status()
                return await response.text()
        except (aiohttp.ClientResponseError, aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
            if response and response.status == 429 and attempt == retries - 1:
                # Log the rate limit error and stop further attempts
                print(f"Rate limit exceeded, aborting task. Error: {e}")
                raise e
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

async def parse_post_page(post_url):
    html_content = await fetch_page(post_url)
    if not html_content:
        return {}

    soup = BeautifulSoup(html_content, 'html.parser')
    
    post_data = {
        'title': soup.select_one('header.post__header h1.post__title').get_text(strip=True) if soup.select_one('header.post__header h1.post__title') else 'No title',
        'published': soup.select_one('div.post__published').get_text(strip=True) if soup.select_one('div.post__published') else 'No date',
        'content': soup.select_one('div.post__content').get_text(strip=True) if soup.select_one('div.post__content') else 'No content',
        'attachments': []
    }

    videos = soup.select('div.post__body video source')
    for video in videos:
        post_data['attachments'].append(video.get('src'))

    images = soup.select('div.post__files a.fileThumb')
    for image in images:
        post_data['attachments'].append(image.get('href'))

    return post_data

async def parse_gallery_page(html_content, username, max_page):
    soup = BeautifulSoup(html_content, 'html.parser')
    posts = []
    section = soup.select_one('section.site-section.site-section--user')
    
    if section:
        tasks = []
        for element in section.select('article.post-card.post-card--preview'):
            post_link = f"https://coomer.su{element.select_one('a')['href']}" if element.select_one('a') else ''
            if post_link:
                tasks.append(parse_post_page(post_link))
        posts = await asyncio.gather(*tasks)

    return posts

async def get_coomer_data(username, service, max_page=1):
    base_url = f'https://coomer.su/{service}/user/{username}'
    all_posts = []
    incomplete_pages = []

    try:
        for page in range(max_page):
            offset = page * 50
            url = f"{base_url}?o={offset}"
            
            # Check if data is already cached
            cache_key = f"coomer:{service}:{username}:{page}"
            cached_data = await redis.get(cache_key)
            if cached_data:
                print(f"Cache hit for {cache_key}")
                posts = json.loads(cached_data)
            else:
                print(f"Cache miss for {cache_key}. Fetching new data.")
                html_content = await fetch_page(url)
                if html_content:
                    posts = await parse_gallery_page(html_content, username, max_page)
                    # Cache the data for future requests
                    await redis.setex(cache_key, 3600, json.dumps(posts))  # Cache for 1 hour
                else:
                    posts = []
                    incomplete_pages.append(url)  # Track incomplete pages

            all_posts.extend(posts)

    except aiohttp.ClientResponseError:
        # Handle rate limit exception and abort execution
        await cache_incomplete_data(incomplete_pages, username, service)
        return all_posts

    # Cache any remaining incomplete pages
    await cache_incomplete_data(incomplete_pages, username, service)
    return all_posts

async def cache_incomplete_data(pages, username, service):
    for url in pages:
        cache_key = f"incomplete:{service}:{username}"
        incomplete_data = await redis.get(cache_key)
        if incomplete_data:
            incomplete_data = json.loads(incomplete_data)
        else:
            incomplete_data = []

        incomplete_data.append(url)
        await redis.setex(cache_key, 7200, json.dumps(incomplete_data))  # Cache for 2 hours

        print(f"Cached incomplete data for {url}")

@com_app.route('/<service>/<username>')
async def coomer_page(service, username):
    try:
        page = int(request.args.get('page', 1))
        data = await get_coomer_data(username, service, max_page=page)
        return jsonify(data)
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': 'An error occurred while processing your request.'}), 500

@com_app.before_app_serving
async def startup():
    global session
    session = await get_session()

@com_app.after_app_serving
async def shutdown():
    if session:
        await session.close()
