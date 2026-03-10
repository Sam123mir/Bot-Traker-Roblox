# Documentación de la BloxPulse API v2

Bienvenido a la documentación oficial de la API v2 de BloxPulse. Esta versión ha sido diseñada para ser robusta, rápida y fácil de integrar con cualquier sitio web o aplicación externa.

---

## 1. Conceptos Básicos

### URL Base
Todas las peticiones deben realizarse a la siguiente base:
`https://bot-traker-roblox.onrender.com/api/v2`

### Formato de Respuesta (Envelope)
Todas las respuestas de la v2 utilizan un formato JSON estandarizado para que tu código siempre sepa qué esperar:

```json
{
  "ok": true,          // Indica si la petición fue exitosa
  "api_version": "2.0.0",
  "timestamp": "ISO-8601",
  "data": { ... },     // El contenido real que solicitaste
  "meta": {
    "request_id": "req_..."
  }
}
```

---

## 2. Autenticación

La mayoría de los endpoints son públicos. Sin embargo, los endpoints administrativos o de estadísticas protegidas requieren una API Key.

**Tipo:** Header  
**Key:** `X-API-Key`  
**Ejemplo:** `X-API-Key: blxp_live_xxxxxxxx`

---

## 3. Endpoints Disponibles

### `GET /platforms`
Devuelve la lista de plataformas soportadas con sus colores, iconos y emojis oficiales.
- **Uso:** Ideal para generar la interfaz visual de tu web sincronizada con el bot.

### `GET /status`
Devuelve la versión actual y el estado de salud de todas las plataformas.
- **Parámetros opcionales:** `?platform=WindowsPlayer` para filtrar.
- **Uso:** Panel de estado en tiempo real.

### `GET /versions`
Historial completo de versiones detectadas.
- **Parámetros:**
  - `limit`: Cantidad de resultados (max 100, default 20)
  - `offset`: Para paginación.
  - `platform`: Filtrar por plataforma.
- **Uso:** Feed de noticias o historial de actualizaciones.

### `GET /widget`
Endpoint "todo-en-uno" diseñado específicamente para el carrusel o footer de tu web. Devuelve tarjetas pre-formateadas con toda la información visual necesaria.

### `GET /stats` (Requiere API Key)
Métricas internas del sistema, conteo de servidores y latencia del bot.

### `GET /health` y `/ready`
Probes básicos para verificar que la API está viva y conectada a la base de datos.

---

## 4. Ejemplos de Uso

### JavaScript (Fetch)
```javascript
async function getBloxPulseStatus() {
  const response = await fetch('https://api.bloxpulse.dev/api/v2/status');
  const body = await response.json();
  
  if (body.ok) {
    console.log("Versión de Windows:", body.data.platforms.WindowsPlayer.version);
  } else {
    console.error("Error:", body.error.message);
  }
}
```

### cURL
```bash
curl -X GET "https://api.bloxpulse.dev/api/v2/stats" \
     -H "X-API-Key: tu_api_key_aqui"
```

---

## 5. Códigos de Error

Si `ok` es `false`, la API devolverá un objeto `error`:

| Código | Descripción |
|---|---|
| `UNAUTHORIZED` | La API Key falta o es incorrecta. |
| `PLATFORM_NOT_FOUND` | El nombre de la plataforma no existe. |
| `INVALID_PARAM` | Los parámetros (limit, offset) no son válidos. |
| `RATE_LIMITED` | Demasiadas peticiones. Intenta de nuevo en unos segundos. |
