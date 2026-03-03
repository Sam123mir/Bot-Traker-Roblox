# X-Blaze | Roblox Version Monitor

Monitor de versiones de Roblox profesional con historial, comparativas y notificaciones multilingües.

## 🚀 Despliegue: GitHub + Webhost + UptimeRobot (24/7 Gratis)

Esta es la mejor forma de mantener el bot siempre online sin tarjeta y sin costos.

### 1. Preparación en GitHub
1. Crea un repositorio en **GitHub** (puede ser privado).
2. Sube todos los archivos (el bot ahora incluye un servidor **Flask** interno).
    - *Nota: El `.gitignore` evitará que subas archivos pesados o privados.*

### 2. Elegir Webhost (Render o similar)
1. Conecta tu repositorio a un servicio como **Render**, **Koyeb** o **Railway**.
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `python bot.py` (o `gunicorn bot:app` si usas un web-worker puro).
4. El bot levantará una web en el puerto `8080`.

### 3. Configurar UptimeRobot (El truco 24/7)
1. Crea una cuenta en [UptimeRobot.com](https://uptimerobot.com/).
2. Añade un **New Monitor**:
    - **Monitor Type**: HTTP(s)
    - **URL**: La URL que te dio tu Webhost (ej: `https://tu-bot.onrender.com`).
    - **Interval**: Cada 5 minutos.
3. Esto enviará una señal a Flask cada 5 minutos, impidiendo que el servidor "se duerma".

## 🛠️ Comandos

- `/version`: Historial de los últimos 7 días.
- `/check`: Estado actual de plataformas.
- `/download`: Links de descarga directa.
- `/compare`: Compara versiones.
- `/ping`: Latencia y diagnóstico.

## 📁 Estructura

- `core/`: Lógica de detección e historial.
- `data/`: JSONs de persistencia.
- `logs/`: Logs del sistema.
- `bot.py`: Punto de entrada principal.

---

## ⚡ Instalación rápida

```bash
pip install -r requirements.txt
```

---

## 🚀 Uso

### Iniciar el monitor
```bash
python monitor.py
```

### Probar todos los embeds
```bash
python test_embeds.py
```

### Probar solo una plataforma
```bash
python test_embeds.py WindowsPlayer
python test_embeds.py iOS
```

---

## ⚙️ Configuración (`config.py`)

| Variable | Descripción | Default |
|---|---|---|
| `WEBHOOK_URL` | Webhook principal de Discord | — |
| `WEBHOOK_LOGS_URL` | Webhook para errores (opcional) | `None` |
| `CHECK_INTERVAL` | Segundos entre chequeos | `300` (5 min) |
| `HEARTBEAT_EVERY` | Segundos entre logs de vida | `3600` (1 hora) |
| `RETRY_ATTEMPTS` | Reintentos ante error de red | `3` |

---

## 🖥️ Plataformas soportadas

| Clave | Plataforma | Fuente de datos |
|---|---|---|
| `WindowsPlayer` | Windows PC | Roblox Client Settings API |
| `MacPlayer` | macOS | Roblox Client Settings API |
| `AndroidApp` | Android | Roblox Client Settings API |
| `iOS` | iPhone / iPad | Apple iTunes Lookup API |

---

## 🌐 Endpoints utilizados

- **Windows / Mac / Android:** `https://clientsettings.roblox.com/v2/client-version/{key}`
- **iOS:** `https://itunes.apple.com/lookup?bundleId=com.roblox.roblox&country=us`

---

## 🛡️ Características

- Escritura atómica en `versions.json` (sin corrupción ante reinicios)
- Reintentos automáticos con backoff ante errores de red
- Manejo de rate-limit de Discord (429)
- Apagado limpio con `Ctrl+C` o señal `SIGTERM`
- Log dual: consola + archivo `monitor.log`
- Embed de inicio al arrancar el bot
- Embed de errores críticos (webhook separado opcional)