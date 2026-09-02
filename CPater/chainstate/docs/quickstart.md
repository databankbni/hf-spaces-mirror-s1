# CHAINSTATE Quick Start Guide

Get up and running with CHAINSTATE in 5 minutes.

## Prerequisites

- Python 3.11+
- Node.js 18+
- Git
- 8GB+ RAM
- (Optional) CUDA-capable GPU

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/CPater/chainstate.git
cd chainstate
```

### 2. Install Python Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install Node Dependencies

```bash
npm install
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

## Running Locally

### Start the API Server

```bash
python -m src.api.server
```

Server will start on `http://localhost:7860`

### Run Tests

```bash
pytest tests/ -v
```

### Launch HF Space UI

```bash
python -m http.server 7860
# Open http://localhost:7860/chainstate.html
```

## Deploying to Cloudflare Workers

### 1. Authenticate

```bash
npx wrangler login
```

### 2. Create KV Namespaces

```bash
npx wrangler kv:namespace create CHAINSTATE_CACHE
npx wrangler kv:namespace create CHAINSTATE_NODES
npx wrangler kv:namespace create CHAINSTATE_CONSENSUS
```

### 3. Update wrangler.toml

Replace the namespace IDs in `wrangler.toml` with your created namespaces.

### 4. Deploy

```bash
npm run deploy
```

## Deploying to Hugging Face Spaces

### 1. Create Space

Go to https://huggingface.co/spaces/CPater/chainstate

### 2. Upload Files

```bash
git clone https://huggingface.co/spaces/CPater/chainstate
cp chainstate.html chainstate/
cd chainstate
git add .
git commit -m "Initial CHAINSTATE deployment"
git push
```

## First Query

### Using curl

```bash
curl -X POST https://your-worker.your-subdomain.workers.dev/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "∫∂x → ?",
    "consensusDepth": 3,
    "swarmSize": 50
  }'
```

### Using Python

```python
import requests

response = requests.post(
    "https://your-worker.your-subdomain.workers.dev/query",
    json={
        "query": "☉☽☿ in alchemy",
        "consensusDepth": 3,
        "swarmSize": 50,
        "quantumOffload": "ibm"
    }
)

print(response.json())
```

### Using JavaScript

```javascript
const response = await fetch('https://your-worker.your-subdomain.workers.dev/query', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: '🧬🔬⚗ → ?',
    consensusDepth: 3,
    swarmSize: 50
  })
});

const result = await response.json();
console.log(result);
```

## Running a Swarm Node

### 1. Register Node

```python
from chainstate.swarm import SwarmNode
from chainstate.symbolic import UniversalSemioticEmbedding

# Initialize
embedding = UniversalSemioticEmbedding()
node = SwarmNode(
    node_id="my-node-001",
    embedding_model=embedding,
    inference_fn=my_inference_function,
    endpoint="https://my-node.example.com"
)

# Register with beacon
await node.register("https://chainstate-beacon.workers.dev")
```

### 2. Start Processing

```python
await node.start_listening()
```

## Development

### Project Structure

```
chainstate/
├── src/
│   ├── symbolic/          # Universal Semiotic Embedding
│   ├── consensus/         # Proof-of-Cognitive-Work
│   ├── chain/             # Blockchain logic
│   ├── quantum/           # Quantum integration
│   └── edge/              # Edge computing
├── workers/               # Cloudflare Workers
├── contracts/             # Smart contracts
├── tests/                 # Test suite
└── docs/                  # Documentation
```

### Running Tests

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest --cov=src --cov-report=html
```

### Code Style

```bash
# Format code
black src/
isort src/

# Type checking
mypy src/

# Linting
flake8 src/
```

## Troubleshooting

### Issue: Out of memory

**Solution:** Reduce batch size or use CPU instead of GPU

```python
# In .env
DEVICE=cpu
BATCH_SIZE=16
```

### Issue: Worker deployment fails

**Solution:** Check wrangler.toml configuration

```bash
npx wrangler config list
npx wrangler whoami
```

### Issue: Query timeout

**Solution:** Increase timeout or reduce swarm size

```python
response = requests.post(
    url,
    json={"swarmSize": 10},  # Reduce from 50
    timeout=60  # Increase from default 30
)
```

## Next Steps

- Read the [Whitepaper](docs/whitepaper.md)
- Explore [API Documentation](docs/api.md)
- Join the [Discord](https://discord.gg/chainstate)
- Contribute on [GitHub](https://github.com/CPater/chainstate)

## Support

- GitHub Issues: https://github.com/CPater/chainstate/issues
- Email: chainstate@nwo.capital
- Telegram: @chainstate_dev

---

**Happy building!** 🚀⛓
