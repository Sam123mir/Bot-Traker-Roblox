import sys
import os
sys.path.append(os.getcwd())

from core.storage import update_version, get_version_data

# Test Windows
update_version("WindowsPlayer", "version-win1", is_official=True)
# Test Android
update_version("AndroidApp", "android-1", is_official=True)

win_state = get_version_data("WindowsPlayer")
and_state = get_version_data("AndroidApp")

print(f"Windows Current: {win_state['current']}")
print(f"Windows History: {win_state['history']}")
print(f"Android Current: {and_state['current']}")
print(f"Android History: {and_state['history']}")

assert "android-1" not in win_state['history']
assert "version-win1" not in and_state['history']
print("\n✓ Storage isolation verified!")
