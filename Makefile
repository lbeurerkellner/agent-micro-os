.PHONY: dev

dev:
	uv run bin/ash.py --user bob --fsimage vaultdata.db --limit 1.0 --crond

dev-shell:
	uv run bin/ash.py --user bob --fsimage vaultdata.db --limit 1.5

fresh:
	uv run bin/ash.py --user bob --fsimage fresh.db

test:
	uv run pytest -v tests/

include .env
export

deploy:
	rsync -avz --delete \
		--exclude '.venv' \
		--exclude '__pycache__' \
		--exclude '*.pyc' \
		--exclude '.git' \
		--exclude '.env' \
		--exclude '*.db' \
		--exclude 'passwd.txt' \
		./ $(DEPLOY_HOST):$(DEPLOY_PATH)/
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_PATH) && docker compose up -d --build"