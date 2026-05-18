.PHONY: migrate test api web scrape-federal scrape-ny reset-db

DB := db/axiom_bills.sqlite

migrate:
	mkdir -p db
	sqlite3 $(DB) < db/migrations/001_init.sql
	@echo "Migrated $(DB)"

reset-db:
	rm -f $(DB)
	$(MAKE) migrate

test:
	cd packages/scrapers && .venv/bin/python -m pytest -q

scrape-federal:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us --limit 50

scrape-ny:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-ny --limit 50

api:
	cd packages/api && .venv/bin/python -m uvicorn axiom_bills_api.main:app --reload --port 8000

web:
	cd packages/web && npm run dev
