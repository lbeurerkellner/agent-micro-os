.PHONY: dev

dev:
	uv run bin/ash.py --user bob --fsimage vaultdata.db --limit 0.50

fresh:
	uv run bin/ash.py --user bob --fsimage fresh.db
