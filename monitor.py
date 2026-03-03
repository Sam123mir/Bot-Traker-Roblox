#!/usr/bin/env python3
# ============================================================
#   X-Blaze | Roblox Version Monitor — monitor.py
#   Bucle principal 24/7 de detección de cambios.
#
#   Uso:
#       python monitor.py
# ============================================================

from __future__ import annotations

import logging
import signal
import sys
import time
import traceback
from datetime import datetime, timezone

import config
import core.storage as storage
from core.checker import fetch_all, VersionInfo
from core.notifier import notify_update, notify_startup, notify_error

# ── Logging ───────────────────────────────────────────────────

def _setup_logging() -> None:
    fmt = "[%(asctime)s] [%(levelname)-8s] %(name)s — %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)


logger = logging.getLogger("monitor")

# ── Señales del SO ────────────────────────────────────────────

_running = True

def _handle_signal(sig, _frame):
    global _running
    logger.info("Señal %s recibida — apagando el monitor de forma segura...", sig)
    _running = False

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Lógica principal ──────────────────────────────────────────

def _check_cycle(stored: dict) -> dict:
    """
    Obtiene las versiones actuales, compara con las almacenadas
    y notifica cambios. Devuelve el estado actualizado.
    """
    current_versions = fetch_all()

    for key, vi in current_versions.items():
        if vi is None:
            logger.warning("No se pudo obtener versión para %s", key)
            continue

        prev_hash = stored.get(key)

        if prev_hash is None:
            # Primera vez que vemos esta plataforma — registrar sin notificar
            logger.info("Primera detección de %s: %s", key, vi)
            stored[key] = vi.version_hash

        elif prev_hash != vi.version_hash:
            logger.info(
                "🆕 Cambio detectado en %s: %s → %s",
                key, prev_hash, vi.version_hash,
            )
            ok = notify_update(key, vi, prev_hash=prev_hash)
            if ok:
                stored[key] = vi.version_hash
            else:
                logger.error("No se actualizó el estado de %s por fallo en webhook.", key)
        else:
            logger.debug("Sin cambios en %s (%s)", key, vi.version)

    return stored


def main() -> None:
    _setup_logging()
    logger.info("=" * 60)
    logger.info("  X-Blaze · Roblox Version Monitor — Iniciando")
    logger.info("  Intervalo de chequeo: %ds | Plataformas: %s",
                config.CHECK_INTERVAL, list(config.PLATFORMS.keys()))
    logger.info("=" * 60)

    # ── Carga inicial ─────────────────────────────────────────
    stored = storage.load()
    logger.info("Estado almacenado cargado: %s entradas", len(stored))

    # ── Notificación de arranque ──────────────────────────────
    startup_versions = fetch_all()
    notify_startup(startup_versions)
    logger.info("Embed de inicio enviado a Discord.")

    # Registrar versiones iniciales si no existen
    for key, vi in startup_versions.items():
        if vi and key not in stored:
            stored[key] = vi.version_hash
    storage.save(stored)

    # ── Bucle principal ───────────────────────────────────────
    last_heartbeat = time.monotonic()

    while _running:
        cycle_start = time.monotonic()

        try:
            stored = _check_cycle(stored)
            storage.save(stored)
        except Exception:
            tb = traceback.format_exc()
            logger.error("Error crítico detectado:\n%s", tb)
            try:
                notify_error(tb)
            except Exception:
                pass

        # Heartbeat log cada HEARTBEAT_EVERY segundos
        now = time.monotonic()
        if now - last_heartbeat >= config.HEARTBEAT_EVERY:
            logger.info("◈ Heartbeat: Sistema activo. Próximo chequeo en %ds.", config.CHECK_INTERVAL)
            last_heartbeat = now

        # Espera hasta el siguiente ciclo
        elapsed = time.monotonic() - cycle_start
        sleep_time = max(0, config.CHECK_INTERVAL - elapsed)
        # Solo loggear debug para no saturar consola
        # logger.debug("Ciclo completado en %.2fs. Esperando %.0fs.", elapsed, sleep_time)

        # Espera en fragmentos para responder rápido a señales
        deadline = time.monotonic() + sleep_time
        while _running and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    logger.info("Monitor detenido correctamente. ¡Hasta pronto!")


if __name__ == "__main__":
    main()