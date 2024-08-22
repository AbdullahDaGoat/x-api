# To run: python -m hypercorn main.py:app --bind 0.0.0.0:5000
from twitter import twitter_app, run_background_caching, process_request_queue
from com import com_app
from ph import ph_app
import asyncio
from threading import Thread
from quart import Quart

# Create a main Quart app
app = Quart(__name__)

# Register Blueprints for Twitter, Coomer, and PornHub
app.register_blueprint(twitter_app, url_prefix="/twitter")
app.register_blueprint(com_app, url_prefix="/coomer")
app.register_blueprint(ph_app, url_prefix="/pornhub")

if __name__ == "__main__":
    # Start background caching in a separate thread for Twitter
    background_thread = Thread(target=run_background_caching)
    background_thread.start()

    # Start processing the request queue for Twitter in the main event loop
    asyncio.run(process_request_queue())

    # Run the app
    app.run(host="0.0.0.0", port=5000, debug=True)
