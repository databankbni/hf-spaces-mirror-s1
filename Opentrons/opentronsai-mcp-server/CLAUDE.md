# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Gradio-based MCP (Model Context Protocol) server that exposes a simple letter counter function. The project demonstrates how to create Gradio interfaces that can be used as MCP servers, enabling AI agents to call the interface functions programmatically.

## Architecture

- **[app.py](app.py)**: Main application file containing the `letter_counter` function wrapped in a Gradio Interface with `mcp_server=True` enabled
- **[app_orig.py](app_orig.py)**: Original chatbot template using HuggingFace Inference API (reference/backup)

The key architectural pattern is that Gradio interfaces launched with `mcp_server=True` expose their functions via MCP, allowing them to be called by AI assistants like Claude.

## Development Environment

**Python virtual environment setup:**
```bash
python -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate    # On Windows
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Run the application:**
```bash
python app.py
```

## Key Dependencies

- `gradio[mcp]`: Gradio with MCP server support
- `anthropic`: Anthropic API client (for Claude integration)
- `chromadb`: Vector database
- `openai`: OpenAI API client
- `python-dotenv`: Environment variable management
- `pytest`: Testing framework
- `wandb`, `weave`: Experiment tracking

## Environment Variables

The project uses a `.env` file (gitignored) for configuration. Ensure required API keys and credentials are set before running.

## Testing

Run tests with pytest:
```bash
pytest
```
