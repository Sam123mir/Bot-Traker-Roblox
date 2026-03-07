import os
import threading
from flask import Flask, jsonify, request
from config import BOT_VERSION
from core.storage import get_version_data, get_all_guilds, get_announcements
from systems.monitoring import API_STATUS

# Mapping for the API status endpoint
API_PLATFORM_MAPPING = {
    "win": "WindowsPlayer",
    "mac": "MacPlayer",
    "android": "AndroidApp",
    "ios": "iOS",
}

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    """Enable CORS for frontend integration."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

@app.route('/')
def home():
    """Simple health check and redirect info."""
    return jsonify({
        "status": "active",
        "service": "BloxPulse API",
        "version": BOT_VERSION,
        "endpoints": ["/api/v1/status", "/api/v1/stats", "/api/v1/history"]
    })

@app.route('/api/v1/status')
def api_status():
    """Returns real-time status of all monitored platforms."""
    status_data = {}
    for choice, platform_key in API_PLATFORM_MAPPING.items():
        state = get_version_data(platform_key)
        status_data[platform_key] = {
            "version": state.get("current", "Unknown"),
            "hash": state.get("last_update", "Unknown"),
            "last_build": state.get("last_build", ""),
            "online": API_STATUS.get(platform_key, True),
            "updated_at": state.get("timestamps", {}).get(state.get("current"), "Unknown")
        }
    return jsonify(status_data)

@app.route('/api/v1/stats')
def api_stats():
    """Returns global bot usage statistics."""
    guilds = get_all_guilds()
    return jsonify({
        "server_count": len(guilds),
        "total_tracked_versions": sum(len(get_version_data(p).get("history", [])) for p in API_PLATFORM_MAPPING.values()),
        "status": "stable"
    })

@app.route('/api/v1/history')
def api_history():
    """Returns the most recent official announcements/updates."""
    limit = request.args.get('limit', default=10, type=int)
    all_updates = get_announcements()
    return jsonify({
        "success": True,
        "updates": all_updates[:limit]
    })

def run_web_server():
    """Start the Flask server on the configured port."""
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def start_api():
    """Starts the API in a background thread."""
    threading.Thread(target=run_web_server, daemon=True).start()
