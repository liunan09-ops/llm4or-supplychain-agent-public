.PHONY: install test lint demo serve eval eval-v2 eval-v2-llm rag-v2 docker-build

install:
	uv sync --extra dev --frozen
test:
	uv run --frozen pytest
lint:
	uv run --frozen ruff check src tests
demo:
	uv run --frozen supplychain demo
serve:
	uv run --frozen supplychain serve
eval:
	uv run --frozen supplychain evaluate --mode rules --split dev --output-dir reports/rules-dev
eval-v2:
	uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode demo --output evaluation/runs_v2/dev_demo_final.json
eval-v2-llm:
	uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode llm --output evaluation/runs_v2/dev_llm_final.json
rag-v2:
	uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/retrieval_heldout_v2.jsonl --mode retrieval --output evaluation/runs_v2/retrieval_heldout.json
docker-build:
	docker build -t supplychain-agent:v2 .
