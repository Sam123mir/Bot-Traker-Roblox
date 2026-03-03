#!/usr/bin/env python3
# ============================================================
#   X-Blaze | Roblox Version Monitor — test_embeds.py
#   Previsualiza todos los embeds en Discord sin iniciar
#   el monitor completo. Ideal para validar el diseño.
#
#   Uso:
#       python test_embeds.py [platform_key]
#       python test_embeds.py WindowsPlayer
#       python test_embeds.py              ← prueba todas
# ============================================================

from __future__ import annotations

import sys
import os
import time

# Allow running from tests/ subfolder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.checker import VersionInfo
from config import PLATFORMS
from core.notifier import notify_update, notify_startup

# ── Datos de prueba por plataforma ────────────────────────────

MOCK_VERSIONS: dict[str, VersionInfo] = {
    "WindowsPlayer": VersionInfo(
        platform_key="WindowsPlayer",
        version="0.710.1.7100707",
        version_hash="version-760d064d05424689",
        channel="LIVE",
        source="Roblox Client Settings API",
    ),
    "MacPlayer": VersionInfo(
        platform_key="MacPlayer",
        version="0.710.1.7100707",
        version_hash="version-99769ee4146d4ccf",
        channel="LIVE",
        source="Roblox Client Settings API",
    ),
    "AndroidApp": VersionInfo(
        platform_key="AndroidApp",
        version="2.710.707",
        version_hash="version-a1b2c3d4e5f60123",
        channel="LIVE",
        source="Roblox Client Settings API",
    ),
    "iOS": VersionInfo(
        platform_key="iOS",
        version="2.710.707",
        version_hash="appstore-2_710_707",
        channel="App Store",
        source="Apple iTunes Lookup API",
    ),
}

MOCK_PREV_HASHES: dict[str, str] = {
    "WindowsPlayer": "version-aaaa1111bbbb2222",
    "MacPlayer":     "version-cccc3333dddd4444",
    "AndroidApp":    "version-eeee5555ffff6666",
    "iOS":           "appstore-2_709_001",
}


def run_test(keys: list[str]) -> None:
    print(f"\n{'─'*55}")
    print(f"  X-Blaze · Test de Embeds")
    print(f"  Plataformas a probar: {keys}")
    print(f"{'─'*55}\n")

    for key in keys:
        if key not in MOCK_VERSIONS:
            print(f"⚠️  Plataforma desconocida: '{key}'. Opciones: {list(PLATFORMS.keys())}")
            continue

        vi        = MOCK_VERSIONS[key]
        prev_hash = MOCK_PREV_HASHES.get(key)

        print(f"📤  Enviando embed de actualización para {PLATFORMS[key]['label']}...")
        ok = notify_update(key, vi, prev_hash=prev_hash)
        status = "✅ Enviado" if ok else "❌ Error"
        print(f"    {status}")

        # Pequeña pausa para no saturar el webhook
        if key != keys[-1]:
            time.sleep(1.5)

    # Embed de inicio
    print(f"\n📤  Enviando embed de inicio del monitor...")
    notify_startup(MOCK_VERSIONS)
    print("    ✅ Enviado\n")
    print("Prueba finalizada. Revisa tu canal de Discord.")


if __name__ == "__main__":
    requested = sys.argv[1:] or list(PLATFORMS.keys())
    run_test(requested)