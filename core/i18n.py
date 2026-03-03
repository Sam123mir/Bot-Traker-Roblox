# ============================================================
#   X-Blaze | Roblox Version Monitor — i18n.py
#   Sistema de internacionalización (Traducciones).
# ============================================================

TRANSLATIONS = {
    "es": {
        "update_title": "¡Roblox {platform} actualizado!",
        "intro_1": "*Roblox ha desplegado una nueva compilación para **{platform}**.*",
        "intro_2": "*Esta versión ya se encuentra operativa en los servidores de producción.*",
        "version": "Versión",
        "platform": "Plataforma",
        "build_hash": "Build Hash",
        "source": "Fuente",
        "download_header": "Descarga Directa",
        "history_header": "Historial de Versiones",
        "startup_title": "Monitor X-Blaze Inicializado",
        "startup_desc": "El sistema de vigilancia está activo y monitoreando cambios en tiempo real.",
        "download_windows": "Enlace de Descarga (Windows)",
        "download_macos": "Enlace de Descarga (macOS)",
        "view_playstore": "Ver en Google Play",
        "view_appstore": "Ver en App Store",
    },
    "en": {
        "update_title": "Roblox {platform} Updated!",
        "intro_1": "*Roblox has deployed a new build for **{platform}**.*",
        "intro_2": "*This version is now operational on production servers.*",
        "version": "Version",
        "platform": "Platform",
        "build_hash": "Build Hash",
        "source": "Source",
        "download_header": "Direct Download",
        "history_header": "Version History",
        "startup_title": "X-Blaze Monitor Initialized",
        "startup_desc": "Watching system is active and monitoring changes in real-time.",
        "download_windows": "Download Link (Windows)",
        "download_macos": "Download Link (macOS)",
        "view_playstore": "View on Google Play",
        "view_appstore": "View on App Store",
    },
    "pt": {
        "update_title": "Roblox {platform} Atualizado!",
        "intro_1": "*Roblox implantou uma nova compilação para **{platform}**.*",
        "intro_2": "*Esta versão já está operacional nos servidores de produção.*",
        "version": "Versão",
        "platform": "Plataforma",
        "build_hash": "Build Hash",
        "source": "Fonte",
        "download_header": "Download Direto",
        "history_header": "Histórico de Versões",
        "startup_title": "Monitor X-Blaze Inicializado",
        "startup_desc": "O sistema de vigilância está ativo e monitorando mudanças em tempo real.",
        "download_windows": "Link de Download (Windows)",
        "download_macos": "Link de Download (macOS)",
        "view_playstore": "Ver no Google Play",
        "view_appstore": "Ver na App Store",
    },
    "ru": {
        "update_title": "Roblox {platform} обновлен!",
        "intro_1": "*Roblox развернул новую сборку для **{platform}**.*",
        "intro_2": "*Эта версия теперь работает на рабочих серверах.*",
        "version": "Версия",
        "platform": "Платформа",
        "build_hash": "Build Hash",
        "source": "Источник",
        "download_header": "Прямая загрузка",
        "history_header": "История версий",
        "startup_title": "Монитор X-Blaze инициализирован",
        "startup_desc": "Система наблюдения активна и отслеживает изменения в реальном времени.",
        "download_windows": "Ссылка на скачивание (Windows)",
        "download_macos": "Ссылка на скачивание (macOS)",
        "view_playstore": "Открыть в Google Play",
        "view_appstore": "Открыть в App Store",
    },
    "fr": {
        "update_title": "Roblox {platform} Mis à jour !",
        "intro_1": "*Roblox a déployé una nouvelle version pour **{platform}**.*",
        "intro_2": "*Cette version est désormais opérationnelle sur les serveurs de production.*",
        "version": "Version",
        "platform": "Plateforme",
        "build_hash": "Build Hash",
        "source": "Source",
        "download_header": "Téléchargement Direct",
        "history_header": "Historique des Versions",
        "startup_title": "Moniteur X-Blaze Initialisé",
        "startup_desc": "Le système de surveillance est actif et surveille les changements en temps réel.",
        "download_windows": "Lien de téléchargement (Windows)",
        "download_macos": "Lien de téléchargement (macOS)",
        "view_playstore": "Voir sur Google Play",
        "view_appstore": "Voir sur l'App Store",
    }
}

def get_text(lang: str, key: str, **kwargs) -> str:
    """Gets a translated string, falling back to English if not found."""
    lang_dict = TRANSLATIONS.get(lang.lower(), TRANSLATIONS["en"])
    text = lang_dict.get(key, TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text
