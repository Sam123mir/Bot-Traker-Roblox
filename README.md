# X-Blaze | Roblox Version Monitor

Monitor de versiones de Roblox profesional con historial, comparativas y notificaciones multilingües.

## 🚀 Despliegue: Render + UptimeRobot (24/7 Gratis)

Render es la opción más sencilla y confiable para este bot.

### 1. Preparación en GitHub
1. Asegúrate de que tu código esté en tu repositorio: `https://github.com/Sam123mir/Bot-Traker-Roblox.git`.
2. He incluido un **Dockerfile** para que Render lo detecte y despliegue sin errores de entorno.

### 2. Configuración en Render
1. Crea un **New Web Service**.
2. **Repository**: Conecta tu repositorio de GitHub.
3. **Runtime**: Selecciona **Docker** (Render detectará automáticamente el archivo `Dockerfile` que creamos).
4. **Plan**: Elige el **Free Plan**.
5. **Environment Variables**:
    - `DISCORD_BOT_TOKEN`: Tu token de Discord.
6. **Despliegue**: Dale a "Create Web Service".

### 3. Evitar que se duerma (UptimeRobot)
Render apaga los servicios gratuitos tras 15 minutos sin visitas.
1. Copia la URL que te dio Render (ej: `https://tu-bot.onrender.com`).
2. Ve a [UptimeRobot.com](https://uptimerobot.com/) y crea un monitor **HTTP(s)** con esa URL cada 5 minutos.
3. Esto mantendrá al bot despierto las 24 horas del día.

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