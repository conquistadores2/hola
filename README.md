# Bot Antinuke para Discord (Python + Railway)

Bot con sistema **antinuke** que detecta y castiga automáticamente acciones
destructivas hechas por cuentas no autorizadas (incluso si tienen permiso de
Administrador de Discord — ese es justamente el punto).

Todos los comandos de configuración funcionan tanto como **slash** (`/comando`)
como con **prefijo de texto** (`!comando` por defecto, configurable). Es el
mismo comando en los dos casos — usa el que te resulte más cómodo.

## Qué protege

| Módulo | Qué detecta |
|---|---|
| `channel_delete` / `channel_create` | Borrado o creación masiva de canales |
| `role_delete` / `role_create` | Borrado o creación masiva de roles |
| `ban` / `kick` | Baneos/expulsiones masivas |
| `webhook_create` | Creación de webhooks (vector clásico de spam/raid) |
| `bot_add` | Bots añadidos por alguien no autorizado (se expulsa al bot al instante) |
| `dangerous_role` | Alguien le da a un miembro un rol con Admin/Ban/Kick/Manage Roles, etc. (se le quita el rol al instante) |
| `guild_update` | Cambios de nombre, ícono o vanity URL del servidor |
| `emoji_delete` | Borrado masivo de emojis |

Cuando algo de esto lo hace alguien que **no** está en la whitelist ni es
admin/dueño del antinuke, el bot le quita todos sus roles y aplica el
castigo configurado (ban por defecto), y lo reporta en el canal de logs.

## 1. Crear la aplicación de Discord

1. Ve a https://discord.com/developers/applications → **New Application**.
2. En la pestaña **Bot** → **Reset Token** → copia el token (lo vas a necesitar en Railway).
3. En esa misma pestaña, activa **SERVER MEMBERS INTENT** y **MESSAGE CONTENT
   INTENT** (los dos son obligatorios). El primero es para detectar altas/bajas
   de miembros; el segundo es para que el bot pueda leer los comandos escritos
   con prefijo (ej. `!whitelist list`). Si solo usaras comandos `/`, no haría
   falta el segundo — pero como este bot soporta ambos, hay que activarlo.
4. En **OAuth2 → URL Generator**: marca el scope `bot` y `applications.commands`.
   En permisos, lo más simple y confiable es marcar **Administrator** (así el
   antinuke nunca se queda sin poder actuar). Si prefieres algo más granular,
   como mínimo necesita: Ver registro de auditoría, Banear miembros, Expulsar
   miembros, Gestionar roles, Gestionar canales, Gestionar webhooks, Enviar
   mensajes, Insertar enlaces.
5. Abre la URL generada e invita el bot a tu servidor.
6. **Importante:** en `Ajustes del servidor → Roles`, arrastra el rol del bot
   **cerca de la cima** de la lista (por encima de cualquier rol que quieras
   que pueda quitar/castigar). Un bot no puede tocar roles por encima del suyo.

## 2. Probar en tu PC (opcional)

```bash
git clone <tu-repo>
cd discord-antinuke-bot
python -m venv .venv
source .venv/bin/activate      # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # y pega tu token dentro
python main.py
```

## 3. Desplegar en Railway

1. Sube esta carpeta a un repositorio de GitHub.
2. En https://railway.app → **New Project → Deploy from GitHub repo** → elige el repo.
3. Railway detecta `requirements.txt` y `Procfile` automáticamente y lo corre
   como *worker* (proceso siempre activo, no necesita puerto público).
4. Ve a la pestaña **Variables** del servicio y agrega:
   - `DISCORD_TOKEN` = el token que copiaste antes
   - `DATA_DIR` = `/data` (ver el paso del Volume abajo)
   - `COMMAND_PREFIX` = `!` (opcional; cambia el prefijo de texto, ej. `?` o `-`)
5. **Agrega un Volume** (pestaña *Volumes* del servicio) montado en `/data`.
   Esto es importante: sin un Volume, la whitelist y la configuración se
   **borran** cada vez que Railway vuelve a desplegar el servicio, porque el
   disco es temporal. Con el Volume, quedan guardadas para siempre.
6. Dale **Deploy**. En los logs deberías ver `Antinuke listo`.

> Si Railway no detecta el `Procfile` (a veces pasa con su build system más
> nuevo, Railpack), entra a **Settings → Deploy → Custom Start Command** y
> pon `python main.py` a mano.

## 4. Primeros comandos (dentro de Discord)

**Todos los comandos funcionan de las dos formas** — como slash (`/comando`,
con autocompletado de Discord) o escritos con el prefijo de texto (por
defecto `!`, configurable con `COMMAND_PREFIX`). Es el mismo comando y el
mismo resultado; usa la que prefieras.

Ejecuta esto como dueño del servidor:

```
/antinuke setup canal:#logs-seguridad          !antinuke setup #logs-seguridad
/antinukeadmin add usuario:@TuManoDerecha      !antinukeadmin add @TuManoDerecha
/whitelist add usuario:@TuManoDerecha          !whitelist add @TuManoDerecha
```

- `/antinuke setup` — define el canal donde se reportan los castigos.
- `/antinukeadmin add` — da a alguien permiso para administrar el antinuke
  (whitelist, castigo, módulos). **Solo el dueño puede usar este comando.**
- `/whitelist add` — deja a alguien exento de los castigos del antinuke
  (para tu staff de confianza y otros bots que uses). Lo puede usar el
  dueño o cualquier admin del antinuke.

Otros comandos útiles (formato slash; todos tienen su equivalente con `!`):

```
/antinuke settings              # ver toda la configuración actual
/antinuke punishment tipo:kick  # cambiar el castigo (ban / kick / strip)
/antinuke module modulo:role_create estado:false   # apagar un módulo puntual
/whitelist list
/antinukeadmin list
/help                           # (o "!ayuda") lista todos los comandos
```

## Jerarquía de permisos

1. **Dueño** (el owner real de Discord, o quien quedó guardado como tal):
   control total, único que puede nombrar/quitar admins del antinuke.
2. **Admin del antinuke**: puede manejar whitelist y ajustes, pero no puede
   nombrar a otros admins.
3. **Whitelist**: exento de castigos, sin poder de administración.

Cualquier otra persona —incluso con el permiso "Administrador" de Discord—
será castigada si dispara el antinuke. Es intencional: el objetivo es
proteger el servidor incluso si una cuenta con admin se compromete.

## Limitaciones importantes (léelas)

- El antinuke **castiga y reporta**, pero no reconstruye automáticamente lo
  que se borró (canales, roles) salvo los baneos, que revertir sería tan
  simple como desbanear manualmente si fue un error. Recuperar canales/roles
  con sus permisos exactos no es algo que se pueda automatizar de forma
  confiable, así que revisa el canal de logs y actúa manualmente si hace falta.
- Detectar quién hizo cada cosa depende del **audit log** de Discord, que a
  veces tarda uno o dos segundos en actualizarse. El bot ya espera un poco
  antes de consultarlo, pero en ataques extremadamente rápidos podría no
  alcanzar a identificar al ejecutor a tiempo.
- Los umbrales (ej. "2 canales borrados en 8 segundos") están pensados para
  máxima seguridad. Si tu staff hace tareas masivas legítimas seguido
  (crear/borrar muchos canales o roles de golpe), **agrégalos a la
  whitelist** o van a terminar castigados — es el trade-off de tener
  seguridad estricta.
- Si le quitan al bot su propio rol o lo expulsan/banean, no hay forma de
  que el bot lo evite desde dentro de discord.py; por eso el rol del bot
  debe estar alto en la jerarquía y solo gente de confianza debería tener
  permiso de tocar roles por encima del suyo.
- Este bot no reemplaza el AutoMod nativo de Discord para spam de mensajes o
  de menciones; están pensados para complementarse, no para lo mismo.

## Estructura del proyecto

```
discord-antinuke-bot/
├── main.py                     # arranque del bot
├── cogs/
│   ├── antinuke_events.py      # detección y castigo automático
│   ├── whitelist.py            # /whitelist add|remove|list
│   ├── antinukeadmin.py        # /antinukeadmin add|remove|list
│   └── antinuke.py             # /antinuke setup|settings|punishment|module + /help
├── utils/
│   ├── database.py             # guardado en JSON por servidor
│   ├── permissions.py          # owner_only/admin_only + cog base (guild-only)
│   └── embeds.py               # embeds compartidos (error=rojo, success=verde, info=azul)
├── requirements.txt
├── Procfile
├── .python-version
├── .env.example
└── .gitignore
```

Los 3 cogs de comandos (`whitelist.py`, `antinukeadmin.py`, `antinuke.py`)
heredan de `AntiNukeCogBase` (en `utils/permissions.py`), que exige que el
comando se use dentro de un servidor. Los checks `owner_only()`/`admin_only()`
y los embeds (`error_embed`/`success_embed`/`info_embed`) también se
importan de `utils/`, así que la lógica de permisos y la apariencia no se
repiten en cada archivo.

## Comandos y embeds

Todas las respuestas del bot son embeds (nunca texto plano), con un color
según el resultado:

| Color | Cuándo se usa |
|---|---|
| 🔴 Rojo | Errores: sin permiso, algo no encontrado, argumento inválido, algo que ya estaba en ese estado |
| 🟢 Verde | Se acaba de aplicar un cambio con éxito (agregar, quitar, configurar, activar/desactivar) |
| 🔵 Azul | Solo información: listas, configuración actual, uso de un comando, `/help` |

`/help` (o `!ayuda`) agrupa los comandos por quién los puede usar (dueño /
admin del antinuke / cualquiera), para saber de un vistazo qué está
disponible según el rol.

## Problemas comunes

- **`PrivilegedIntentsRequired`**: activa "SERVER MEMBERS INTENT" **y**
  "MESSAGE CONTENT INTENT" en el Developer Portal (paso 1.3). Faltan los
  dos, no solo uno.
- **`LoginFailure` / token inválido**: reseteá el token en el Developer
  Portal y actualizá la variable `DISCORD_TOKEN` en Railway.
- **Los comandos `/` no aparecen**: pueden tardar hasta 1 hora en
  propagarse la primera vez a nivel global; reiniciar Discord (Ctrl+R)
  suele mostrarlos antes.
- **Los comandos con prefijo (`!comando`) no responden nada**: casi
  siempre es porque falta activar "MESSAGE CONTENT INTENT" en el Developer
  Portal (paso 1.3) — sin ese intent, discord.py no puede leer el texto de
  los mensajes y los ignora en silencio. Los comandos `/` seguirían
  funcionando igual.
- **El bot no castiga a nadie**: revisá que su rol esté por encima del rol
  del que quieres poder castigar, y que tenga permiso de "Ver registro de
  auditoría".
