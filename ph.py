from quart import Blueprint, jsonify, request
from phlib import PornHub
import logging

# Create the Blueprint
ph_app = Blueprint("pornhub", __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_get_attr(obj, attr, default=None):
    """Safely get an attribute from an object, returning a default if not found."""
    return getattr(obj, attr, default)

def video_to_dict(video):
    """Convert a video object to a dictionary, handling missing attributes."""
    return {
        "title": safe_get_attr(video, 'title', 'Unknown Title'),
        "url": safe_get_attr(video, 'url', 'Unknown URL'),
        "duration": str(safe_get_attr(video, 'duration', 'Unknown Duration')),
        "views": safe_get_attr(video, 'views', 'Unknown Views'),
        "rating": safe_get_attr(video, 'rating', 'Unknown Rating'),
        "author": safe_get_attr(video, 'author', 'Unknown Author'),
        "tags": safe_get_attr(video, 'tags', [])
    }

@ph_app.route('/categories', methods=['GET'])
async def get_categories():
    try:
        ph = PornHub()
        categories = ph.categories
        category_list = [{"name": category, "url": ph[category].url} for category in categories]
        return jsonify(category_list)
    except Exception as e:
        logger.error(f"Error in get_categories: {str(e)}")
        return jsonify({"error": "Failed to retrieve categories"}), 500

@ph_app.route('/category/<category_name>/videos', methods=['GET'])
async def get_category_videos(category_name):
    try:
        ph = PornHub()
        max_videos = int(request.args.get('max', 25))
        category = ph[category_name]
        videos = list(category.videos(max=max_videos))
        video_list = [video_to_dict(video) for video in videos]
        return jsonify(video_list)
    except KeyError:
        return jsonify({"error": f"Category '{category_name}' not found"}), 404
    except Exception as e:
        logger.error(f"Error in get_category_videos: {str(e)}")
        return jsonify({"error": "Failed to retrieve videos"}), 500

@ph_app.route('/search', methods=['GET'])
async def search_videos():
    try:
        ph = PornHub()
        search_term = request.args.get('query')
        if not search_term:
            return jsonify({"error": "Search query is required"}), 400
        max_videos = int(request.args.get('max', 25))
        videos = list(ph.search(search_term, max=max_videos))
        video_list = [video_to_dict(video) for video in videos]
        return jsonify(video_list)
    except Exception as e:
        logger.error(f"Error in search_videos: {str(e)}")
        return jsonify({"error": "Failed to perform search"}), 500
