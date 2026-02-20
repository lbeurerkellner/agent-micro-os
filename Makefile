.PHONY: dev

dev:
	uv run bin/ash.py --user bob --fsimage vaultdata.db
