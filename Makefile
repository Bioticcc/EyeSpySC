.PHONY: backend-install check

backend-install:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -e 'backend[dev]'

check:
	./scripts/check.sh
