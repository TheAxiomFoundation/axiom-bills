.PHONY: migrate test api web scrape-federal scrape-ny scrape-co scrape-de scrape-ks scrape-md scrape-mn scrape-oh scrape-or scrape-ut scrape-wi reset-db

DB := db/axiom_bills.sqlite

migrate:
	mkdir -p db
	@for f in db/migrations/*.sql; do \
	  echo "Applying $$f"; \
	  sqlite3 $(DB) < $$f; \
	done
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

scrape-co:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-co --limit 50

scrape-de:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-de --limit 50

scrape-ks:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-ks --limit 50

scrape-md:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-md --limit 50

scrape-mn:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-mn --limit 50

scrape-oh:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-oh --limit 50

scrape-or:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-or --limit 50

scrape-ut:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-ut --limit 50

scrape-wi:
	cd packages/scrapers && .venv/bin/python -m axiom_bills.cli scrape --jurisdiction us-wi --limit 50

api:
	cd packages/api && .venv/bin/python -m uvicorn axiom_bills_api.main:app --reload --port 8001

web:
	cd packages/web && npm run dev
