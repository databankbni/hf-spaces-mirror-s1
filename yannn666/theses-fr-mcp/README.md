---
title: Theses.fr MCP
emoji: 🎓
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
pinned: false
license: mit
---

# theses.fr — recherche (Gradio + MCP)

Interface Gradio permettant d'interroger l'API officielle de [theses.fr](https://theses.fr) (moteur Solr d'ABES) : recherche de thèses par titre, auteur, discipline, mots-clés, etc.

Ce Space est aussi exposé comme **serveur MCP** (Model Context Protocol) : l'URL `.../gradio_api/mcp/` peut être ajoutée directement comme serveur MCP dans un client compatible (Claude Code, Claude Desktop, etc.) pour permettre à un assistant IA d'interroger theses.fr.

API source : https://theses.fr/api/v1/theses/recherche/
