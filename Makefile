.PHONY: backend-install frontend-install desktop-dev sidecar check

backend-install:
	python3.11 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -e 'backend[dev,packaging]'

frontend-install:
	cd desktop && npm ci

# Runs the GUI from source; it uses backend/.venv/bin/eyespysc for counting.
desktop-dev:
	cd desktop && npm run tauri dev

sidecar:
	./scripts/build-linux-sidecars.sh
	./scripts/smoke-packaged-cli.sh backend/dist/sidecars/eyespysc-cli-x86_64-unknown-linux-gnu

check:
	./scripts/check.sh
