import sys
import os
sys.path.append(os.getcwd())

# Before import, guilds.json exists
print(f"Legacy file exists: {os.path.exists('data/guilds.json')}")

# Import storage, which triggers migration
from core.storage import get_all_guilds

print(f"Legacy file exists after migration: {os.path.exists('data/guilds.json')}")
print(f"Migrated file exists: {os.path.exists('data/guilds.json.migrated')}")

all_guilds = get_all_guilds()
print(f"Found {len(all_guilds)} guilds in new storage.")

for gid, cfg in all_guilds.items():
    print(f"Guild {gid}: name={cfg.get('server_name')}, lang={cfg.get('language')}")

# Verify folder structure
servers_dir = 'data/servers'
if os.path.exists(servers_dir):
    print(f"Contents of {servers_dir}: {os.listdir(servers_dir)}")
else:
    print(f"Error: {servers_dir} does not exist!")
