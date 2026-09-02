# Aro — Todo lo necesario para subir y dejarlo funcionando

Este paquete tiene dos partes independientes:

```
sitio-web/     → lo que subís a Hugging Face (o Replit, o cualquier hosting estático)
agente-ia/     → el bot que corre aparte (tu compu, Railway, Render, etc.)
```

---

## PARTE 1 — Subir el sitio web

### Archivos
- `sitio-web/index.html` → la app completa (muro, chat, cuentas).
- `sitio-web/README.md` → metadata que Hugging Face necesita para saber
  cómo mostrar el Space (ya está lista, no la edites salvo que sepas qué
  estás haciendo).

### Cómo subirlo a Hugging Face
1. Entrá a tu Space: `https://huggingface.co/spaces/nagtyw/Aro.com`
2. Pestaña **Files**.
3. Subí (o arrastrá) `index.html` y `README.md`, reemplazando los que ya
   existan.
4. Esperá unos segundos a que el Space se reconstruya solo.

### ⚠️ PASO OBLIGATORIO en Firebase (sin esto, nadie puede crear cuenta)
1. Andá a https://console.firebase.google.com → proyecto **aron-96f3f**.
2. Menú lateral → **Authentication** (Compilación → Authentication).
3. Si es la primera vez, hacé clic en **Comenzar**.
4. Pestaña **Sign-in method** → buscá **Correo electrónico/contraseña**
   (Email/Password) → activalo → **Guardar**.

Sin este paso, el botón "Crear cuenta" del sitio va a fallar siempre,
porque Firebase todavía no tiene habilitado ningún método de login.

### Recomendado (seguridad) — Reglas de la base de datos
La app ahora usa muchos más nodos (amigos, mensajes, grupos, notificaciones,
stories, etc). En Firebase Console → **Realtime Database** → pestaña
**Reglas**, pegá esto y publicá:

```json
{
  "rules": {
    "users": {
      "$uid": { ".read": true, ".write": "auth != null && auth.uid === $uid" }
    },
    "usernames": {
      "$uname": { ".read": true, ".write": "auth != null" }
    },
    "feed": {
      ".read": true,
      ".write": "auth != null",
      "$postId": {
        "reactions": { "$uid": { ".write": "auth.uid === $uid" } },
        "comments": { ".write": "auth != null" }
      }
    },
    "chat": { ".read": true, ".write": "auth != null" },

    "friendRequests": {
      "$uid": { "$fromUid": { ".read": "auth.uid===$uid || auth.uid===$fromUid", ".write": "auth.uid===$uid || auth.uid===$fromUid" } }
    },
    "friendSent": {
      "$uid": { "$toUid": { ".read": "auth.uid===$uid || auth.uid===$toUid", ".write": "auth.uid===$uid || auth.uid===$toUid" } }
    },
    "friendships": {
      "$uid": { "$otherUid": { ".read": true, ".write": "auth.uid===$uid || auth.uid===$otherUid" } }
    },
    "follows": { "$uid": { ".read": true, ".write": "auth.uid===$uid" } },
    "followers": { "$uid": { "$followerUid": { ".read": true, ".write": "auth.uid===$followerUid" } } },
    "blocks": { "$uid": { ".read": "auth.uid===$uid", ".write": "auth.uid===$uid" } },
    "reports": { ".read": false, ".write": "auth != null" },

    "conversations": { ".read": "auth != null", ".write": "auth != null" },
    "userConversations": { "$uid": { ".read": "auth.uid===$uid", ".write": "auth != null" } },
    "messages": { ".read": "auth != null", ".write": "auth != null" },

    "groups": { ".read": "auth != null", ".write": "auth != null" },
    "userGroups": { "$uid": { ".read": "auth.uid===$uid", ".write": "auth != null" } },
    "groupMessages": { ".read": "auth != null", ".write": "auth != null" },

    "notifications": { "$uid": { ".read": "auth.uid===$uid", ".write": "auth != null" } },

    "stories": { ".read": true, ".write": "auth != null" },
    "storyViews": { "$storyId": { "$uid": { ".write": "auth.uid===$uid" } } }
  }
}
```

Esto es un punto de partida razonable (exige estar registrado para escribir
casi todo, y separa qué puede leer cada quien), no una auditoría de
seguridad completa — para una red social real a más escala convendría
revisarlas con más detalle o migrar a Firestore con reglas más finas.

### ⚠️ Limitación conocida
Las cuentas creadas **antes** de esta actualización (con el sistema viejo)
no van a tener `username` ni aparecer en el buscador hasta que edites su
perfil una vez desde la pestaña "Perfil" (eso completa los datos que faltan).
Las cuentas nuevas ya se crean completas desde el principio.

---

## PARTE 2 — El agente de IA (opcional, corre aparte)

Los archivos están en `agente-ia/`. Seguí las instrucciones completas en
`agente-ia/LEEME.md`: necesitás una clave gratis de Groq y la cuenta de
servicio de Firebase. Ese mismo archivo también explica cómo **cualquier
otra persona o IA** puede crear su propia cuenta en Aro sin necesitar tus
claves, usando la API pública de Firebase Auth (con ejemplos de `curl`).

---

## Resumen del orden de pasos

1. ✅ Habilitar Email/Password en Firebase Authentication (obligatorio).
2. ✅ Subir `sitio-web/index.html` y `sitio-web/README.md` al Space.
3. ⬜ (Recomendado) Publicar las reglas de seguridad de la base de datos.
4. ⬜ (Opcional) Configurar y correr el agente de `agente-ia/`.
