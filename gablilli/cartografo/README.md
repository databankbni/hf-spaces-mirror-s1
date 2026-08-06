---
---
title: cartografo
emoji: 🗺️
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---
---

# cartografo

tile server per [condottiero](https://condottiero.insidegubbio.com), la custom instance di [gpx.studio](https://github.com/gpxstudio/gpx.studio) di insidegubbio.

serve tile vettoriali, font e sprite per lo stile aquarelle usato nelle mappe embed di condottiero. i tile vengono scaricati da [protomaps](https://protomaps.com) ad ogni avvio, quindi ad ogni restart si aggiorna automaticamente all'ultima versione disponibile.

## endpoints

| endpoint | descrizione |
|---|---|
| `/style.json` | stile maplibre aquarelle |
| `/tiles/...` | tile vettoriali (via martin) |
| `/fonts/{fontstack}/{range}.pbf` | glyphs per le label |
| `/sprites/sprite.json` | sprite manifest |
| `/sprites/sprite.png` | sprite sheet texture acquerello |
| `/health` | stato del server |

## uso in condottiero

```typescript
// layers.ts
aquarelle: 'https://cartografo.insidegubbio.com/style.json',
```

## stack

- [martin](https://github.com/maplibre/martin) - tile server rust
- [protomaps](https://protomaps.com) - dati osm aggiornati
- [fastapi](https://fastapi.tiangolo.com) - server http unificato
- font satoshi via [fontshare](https://www.fontshare.com/fonts/satoshi) + noto sans come fallback

## note

il primo avvio impiega 10-15 minuti per scaricare i tile italia (~1-2gb). i log sono visibili in tempo reale nella tab logs di huggingface.
