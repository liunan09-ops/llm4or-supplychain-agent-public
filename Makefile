.PHONY: install install-lexical prepare-model test test-lexical lint demo serve serve-lexical eval eval-v2 eval-v2-llm rag-v2 docker-build

PYTHON ?= .venv/bin/python
OUTPUT_ROOT ?= .runtime/evaluations

install:
	uv sync --python 3.12 --extra dev --extra semantic --frozen
install-lexical:
	uv sync --python 3.12 --extra dev --frozen
prepare-model:
	$(PYTHON) scripts/prepare_embeddings.py
	$(PYTHON) scripts/prepare_embeddings.py --verify-only
test:
	RUN_EMBEDDING_INTEGRATION=1 $(PYTHON) -m pytest
test-lexical:
	AGENT_RETRIEVAL_BACKEND=lexical RUN_EMBEDDING_INTEGRATION=0 $(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts
demo:
	$(PYTHON) -m supplychain_agent.cli demo
serve:
	AGENT_RETRIEVAL_BACKEND=hybrid $(PYTHON) -m supplychain_agent.cli serve
serve-lexical:
	AGENT_RETRIEVAL_BACKEND=lexical $(PYTHON) -m supplychain_agent.cli serve
eval:
	$(PYTHON) -m supplychain_agent.cli evaluate --mode rules --split dev --output-dir $(OUTPUT_ROOT)/rules-dev
eval-v2:
	$(PYTHON) -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode demo --output $(OUTPUT_ROOT)/dev_demo.json
eval-v2-llm:
	$(PYTHON) -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode llm --output $(OUTPUT_ROOT)/dev_llm.json
rag-v2:
	$(PYTHON) -m supplychain_agent.v2.evaluation --dataset evaluation/retrieval_heldout_v2.jsonl --mode retrieval --output $(OUTPUT_ROOT)/retrieval_heldout.json
docker-build:
	docker build -t supplychain-agent:v2 .
