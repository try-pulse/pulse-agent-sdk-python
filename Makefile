PYTHON ?= python

.PHONY: check contract lint types test

check: contract lint types test

contract:
	shasum -a 256 -c specs/SHA256SUMS
	$(PYTHON) scripts/generate_types.py --check

lint:
	$(PYTHON) -m ruff check src tests scripts examples

types:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q
