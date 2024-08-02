# python -m hypercorn main:app --bind 0.0.0.0:5000
from quart import Quart
from twitter import get_user_data_route, preflight_cache

app = Quart(__name__)

@app.before_serving
async def start_prefetching():
    app.add_background_task(preflight_cache)

@app.route("/twitter/user/<string:user_login>", methods=["GET"])
async def get_user_data(user_login):
    return await get_user_data_route(user_login)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
