import os
import sys
sys.path.append(os.getcwd())

os.environ["BLOXPULSE_API_KEY"] = "test_key_123"

from api.app import create_app
from api.config import config

if __name__ == "__main__":
    app = create_app(bot=None) # No bot instance for testing
    print(f"Starting API on 0.0.0.0:8081...")
    app.run(host="0.0.0.0", port=8081, debug=True)
