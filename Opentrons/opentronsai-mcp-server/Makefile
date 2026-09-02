KNOWLEDGE_VERSION ?= 9.0.0-k1
ABOUT_MODEL ?= claude-sonnet-5
# Set CLAUDE_ABOUTS=0 for offline extract-only sync.
CLAUDE_ABOUTS ?= 1
PYTHON ?= uv run python

.PHONY: sync-knowledge
sync-knowledge:
ifeq ($(CLAUDE_ABOUTS),0)
	$(PYTHON) -m api.knowledge --version $(KNOWLEDGE_VERSION) --no-claude-abouts
else
	$(PYTHON) -m api.knowledge --version $(KNOWLEDGE_VERSION) --about-model $(ABOUT_MODEL)
endif

.PHONY: local-run
local-run:
	$(PYTHON) app.py

.PHONY: test
test:
	$(PYTHON) -m pytest tests/ -q

MCP_BASE_URL ?= http://127.0.0.1:7860
MAX_SIMULATE_ATTEMPTS ?= 3

.PHONY: test-local-mcp
test-local-mcp:
	$(PYTHON) scripts/test_local_mcp.py --base-url $(MCP_BASE_URL)

.PHONY: test-generate-until-simulates
test-generate-until-simulates:
	$(PYTHON) scripts/test_local_mcp.py --base-url $(MCP_BASE_URL) \
		--generate-until-simulates --max-simulate-attempts $(MAX_SIMULATE_ATTEMPTS)
