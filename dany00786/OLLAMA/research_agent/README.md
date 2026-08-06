# Autonomous Multi-Agent Research System

An intelligent research system built with Python and LangGraph that uses autonomous AI agents to scrape web data and synthesize findings into comprehensive reports. The system integrates with PostgreSQL for historical query storage and implements LLMOps principles to ensure reliable, loop-free execution.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   LangGraph Workflow                         │
│                                                               │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐  │
│  │   Validate   │────▶│  Researcher  │────▶│    Writer    │  │
│  │    Input     │     │    Agent     │     │    Agent     │  │
│  └──────────────┘     └──────────────┘     └──────────────┘  │
│         │                    │                    │           │
│         │                    ▼                    │           │
│         │            Web Scraping                 │           │
│         │            Data Extraction              │           │
│         │                                         │           │
│         └─────────────────────────────────────────┘           │
│                              │                                │
│                              ▼                                │
│                      ┌──────────────┐                         │
│                      │  Finalize &  │                         │
│                      │   Store      │                         │
│                      └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   PostgreSQL DB     │
                    │  - Queries          │
                    │  - Findings         │
                    │  - Reports          │
                    └─────────────────────┘
```

## ✨ Features

- **Multi-Agent Architecture**: Separate Researcher and Writer agents with specialized capabilities
- **Web Scraping**: Automated search and content extraction using DuckDuckGo and Trafilatura
- **Intelligent Synthesis**: LLM-powered report generation with structured analysis
- **PostgreSQL Integration**: Persistent storage for queries, findings, and reports
- **LLMOps Safeguards**: 
  - Loop detection and prevention
  - Timeout management
  - Automatic retries with exponential backoff
  - Execution monitoring and logging
- **CLI Interface**: Easy-to-use command-line interface
- **Markdown Reports**: Professional, well-formatted research reports with citations

## 📋 Requirements

- Python 3.9+
- PostgreSQL (optional, for historical storage)
- Ollama (running locally or remote)

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or navigate to the project directory
cd "Research Agent"

# Install dependencies
pip install -r requirements.txt
```

### 2. Setup Ollama

```bash
# Install Ollama (if not already installed)
# See: https://ollama.com/download

# Pull the model
ollama pull nemotron-3-nano:30b-cloud

# Start Ollama service
ollama serve
```

### 3. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env to configure Ollama URL and model
# Default: http://localhost:11434 with nemotron-3-nano:30b-cloud
```

### 3. Setup PostgreSQL (Optional)

```bash
# Create database
createdb research_db

# The system will automatically create tables on first run
```

### 4. Run Research

```bash
# Basic research query
python main.py research "AI market trends 2024"

# Without database storage
python main.py research "renewable energy innovations" --no-db

# View historical queries
python main.py history --limit 20
```

## 📁 Project Structure

```
Research Agent/
├── agents/
│   ├── __init__.py
│   ├── researcher.py      # Web scraping and data extraction agent
│   └── writer.py          # Report synthesis and generation agent
├── database/
│   ├── __init__.py
│   └── connection.py      # PostgreSQL connection and schema management
├── utils/
│   ├── __init__.py
│   └── llmops.py          # LLMOps monitoring, loop prevention, retries
├── reports/               # Generated research reports (auto-created)
├── workflow.py            # LangGraph workflow orchestration
├── main.py                # CLI entry point
├── requirements.txt       # Python dependencies
├── .env.example          # Environment configuration template
└── README.md             # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | LLM model to use | `nemotron-3-nano:30b-cloud` |
| `DATABASE_HOST` | PostgreSQL host | `localhost` |
| `DATABASE_PORT` | PostgreSQL port | `5432` |
| `DATABASE_NAME` | Database name | `research_db` |
| `DATABASE_USER` | Database user | `postgres` |
| `DATABASE_PASSWORD` | Database password | - |
| `MAX_SCRAPING_RESULTS` | Max search results to scrape | `10` |
| `MAX_RETRIES` | Max retry attempts | `3` |
| `AGENT_TIMEOUT_SECONDS` | Agent execution timeout | `300` |

## 🛡️ LLMOps Features

### Loop Prevention
- Maximum iteration tracking (default: 10)
- Automatic detection of infinite loops
- Graceful failure with detailed error messages

### Timeout Management
- Configurable timeout per agent execution
- Real-time elapsed time tracking
- Prevents runaway processes

### Retry Logic
- Exponential backoff strategy
- Configurable retry limits
- Automatic recovery from transient failures

### Monitoring
- Real-time execution metrics
- Iteration and retry tracking
- Comprehensive logging to `research_system.log`

## 📊 Database Schema

The system maintains three tables:

1. **research_queries**: Stores historical queries with status
2. **research_findings**: Stores scraped content from web sources
3. **research_reports**: Stores generated reports

## 💡 Usage Examples

### Programmatic Usage

```python
from workflow import ResearchWorkflow
from database.connection import DatabaseConnection

# Initialize with database
db = DatabaseConnection()
db.initialize_schema()
workflow = ResearchWorkflow(db_connection=db)

# Execute research
result = workflow.execute("Impact of quantum computing on cybersecurity")

print(f"Status: {result['status']}")
print(f"Findings: {result['findings_count']}")
print(f"Report: {result['report_path']}")
```

### View Historical Queries

```python
from database.connection import DatabaseConnection

db = DatabaseConnection()
queries = db.get_historical_queries(limit=10)

for q in queries:
    print(f"{q['query']} - {q['status']}")
```

## 🔍 How It Works

### 1. Researcher Agent
- Searches DuckDuckGo for relevant sources
- Scrapes web content using Trafilatura and BeautifulSoup
- Uses LLM to extract key findings from raw content
- Stores findings in PostgreSQL

### 2. Writer Agent
- Analyzes research findings
- Generates structured report with:
  - Executive Summary
  - Key Findings (organized by theme)
  - Analysis and Insights
  - Conclusions and Recommendations
  - Source Citations
- Saves report as markdown file
- Stores report in PostgreSQL

### 3. LangGraph Workflow
- Orchestrates agent execution
- Manages state transitions between agents
- Implements checkpointing for reliability
- Ensures sequential, controlled execution

## 🐛 Troubleshooting

### Database Connection Failed
```
Warning: Database initialization failed
```
- PostgreSQL may not be running
- Check credentials in `.env`
- System will continue without database storage

### No Search Results
- Try more specific queries
- Check internet connection
- Verify DuckDuckGo is accessible

### LLM Connection Errors
- Verify Ollama is running: `ollama serve`
- Check model is pulled: `ollama list`
- Verify `OLLAMA_BASE_URL` in `.env` matches your Ollama server
- Review error logs in `research_system.log`

## 📝 Logging

All operations are logged to `research_system.log` with:
- Timestamp
- Component name
- Log level
- Detailed messages

Monitor logs for debugging and performance analysis.

## 🔄 Future Enhancements

- [ ] Add more search engines (Google, Bing APIs)
- [ ] Implement parallel scraping for faster execution
- [ ] Add PDF export capability
- [ ] Support for multi-research queries
- [ ] Web dashboard for visualization
- [ ] Agent self-evaluation and quality scoring
- [ ] Caching layer for frequently researched topics

## 📄 License

MIT License - Feel free to use and modify.

## 🤝 Contributing

Contributions welcome! Please submit issues and pull requests.

## 📧 Support

For issues, questions, or suggestions, please open an issue in the repository.
