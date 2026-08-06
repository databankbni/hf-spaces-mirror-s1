---
title: Luther Bible MCP
emoji: 📖
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Luther Bible MCP Server

Semantic search over the Luther Bible (German, 1545), King James Version, and New Heart English Bible.

Backed by `intfloat/multilingual-e5-small` embeddings and ChromaDB. Cross-lingual search works out of the box — query in English to find German verses, or vice versa.

## Connecting from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "Luther Bible": {
      "type": "sse",
      "url": "https://aifreund-luther-bible.hf.space/sse"
    }
  }
}
```

No API key required. No local install needed.

## Available tools

- `search_bible` — semantic search (any language, optional testament filter)
- `get_verse` — exact lookup by book/chapter/verse
- `list_translations` — list available translations with verse counts
