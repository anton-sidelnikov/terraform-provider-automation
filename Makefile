UV ?= uv
UV_RUN := $(UV) run --frozen
PYTHON := $(UV_RUN) python
RUFF := $(UV_RUN) ruff
export PYTHONPATH := $(CURDIR)/src

.PHONY: sync check verify lint test offline-eval integration-test catalog-check package

sync:
	$(UV) sync --locked --dev

check: lint verify

lint:
	$(RUFF) check src scripts tests

verify:
	$(PYTHON) -m compileall -q src scripts tests
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m otc_agent.cli catalog-check
	$(PYTHON) -m otc_agent.cli policy-check
	$(PYTHON) -m otc_agent.cli skill-check
	$(PYTHON) -m otc_agent.cli eval --mode offline --dataset evals/offline.jsonl --baseline evals/baseline.json --output build/offline-eval.json

test:
	$(PYTHON) -m unittest discover -s tests -v

offline-eval:
	$(PYTHON) -m otc_agent.cli eval --mode offline --dataset evals/offline.jsonl --baseline evals/baseline.json --output build/offline-eval.json

online-eval:
	$(PYTHON) -m otc_agent.cli eval --mode online --dataset evals/online.jsonl --baseline evals/baseline.json --output build/online-eval.json

catalog-check:
	$(PYTHON) -m otc_agent.cli catalog-check

package:
	$(UV) build --wheel --out-dir dist
