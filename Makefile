.PHONY: dev

dev:
	uv run bin/ash.py --user bob --fsimage vaultdata.db

fresh:
	uv run bin/ash.py --user bob --fsimage fresh.db
