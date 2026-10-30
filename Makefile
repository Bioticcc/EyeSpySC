.PHONY: backend-install sidecar check

backend-install:
	python3.11 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -e 'backend[dev,packaging]'

sidecar:
	./scripts/build-linux-sidecars.sh
	./scripts/smoke-packaged-cli.sh backend/dist/sidecars/eyespysc-cli-x86_64-unknown-linux-gnu

check:
	./scripts/check.sh
