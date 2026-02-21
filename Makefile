.PHONY: dev

dev:
	uv run bin/ash.py --user bob --fsimage vaultdata.db --limit 1.0

fresh:
	uv run bin/ash.py --user bob --fsimage fresh.db

test:
	uv run pytest -v tests/