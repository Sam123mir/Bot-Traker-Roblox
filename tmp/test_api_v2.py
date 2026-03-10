# /tmp/test_api_v2.py
import requests
import json

BASE_URL = "http://localhost:8081" # Assuming default port
V1_PREFIX = "/api/v1"
V2_PREFIX = "/api/v2"

def test_v2_platforms():
    print("Testing GET /api/v2/platforms...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/platforms")
    print(f"Status: {r.status_code}")
    print(f"Content: {r.text}")
    data = r.json()
    assert data["ok"] == True
    assert "platforms" in data["data"]
    print("✓ Platforms OK")

def test_v2_status():
    print("Testing GET /api/v2/status...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/status")
    data = r.json()
    assert data["ok"] == True
    assert "platforms" in data["data"]
    print("✓ Status OK")

def test_v2_versions():
    print("Testing GET /api/v2/versions...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/versions?limit=5")
    data = r.json()
    assert data["ok"] == True
    assert len(data["data"]["versions"]) <= 5
    assert "pagination" in data["data"]
    print("✓ Versions OK")

def test_v2_stats():
    print("Testing GET /api/v2/stats (Unauthorised)...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/stats")
    assert r.status_code == 401
    print("✓ Stats Unauthorized OK")

    print("Testing GET /api/v2/stats (Authorised)...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/stats", headers={"X-API-Key": "test_key_123"})
    assert r.status_code == 200
    assert r.json()["ok"] == True
    print("✓ Stats Authorized OK")

def test_v2_widget():
    print("Testing GET /api/v2/widget...")
    r = requests.get(f"{BASE_URL}{V2_PREFIX}/widget")
    data = r.json()
    assert r.status_code == 200
    assert data["ok"] == True
    assert "cards" in data["data"]
    print("✓ Widget OK")

def test_v1_compat():
    print("Testing V1 compatibility (GET /api/v1/status)...")
    r = requests.get(f"{BASE_URL}{V1_PREFIX}/status")
    # V1 doesn't have the 'ok' envelope
    data = r.json()
    assert "WindowsPlayer" in data or "data" in data # v1 might be wrapped depending on current routes.py state
    print("✓ V1 Compatibility OK")

if __name__ == "__main__":
    try:
        test_v2_platforms()
        test_v2_status()
        test_v2_versions()
        test_v2_stats()
        test_v2_widget()
        test_v1_compat()
        print("\nAll tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
