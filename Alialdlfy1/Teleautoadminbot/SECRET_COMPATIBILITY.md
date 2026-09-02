# P29 Secret Compatibility

The existing secret names are intentionally unchanged. Existing deployments can
continue to use environment variables exactly as before.

## Existing names

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `SESSION_STRING`
- `ADMINS` (legacy fallback: `ADMIN_ID`)
- `MIDDLE_CHANNEL`
- `GEMINI_KEY_1`, `GEMINI_KEY_2`, and any additional `GEMINI_KEY_N`
- `GROQ_KEY_1` and any additional `GROQ_KEY_N`
- `OPENROUTER_KEY_1` and any additional `OPENROUTER_KEY_N`
- `BLOGGER_BLOG_ID`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REFRESH_TOKEN`
- `P29_SECRET_MASTER_KEY`

Environment values always have priority. If a value is absent from the
environment, the encrypted SecretManager can supply it. This allows new secrets
to be added at runtime without changing application code.

The master key itself remains an environment/host secret and is never stored
inside the application database.
