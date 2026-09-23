.PHONY: help up down logs data seed train test lint types bench web check demo clean free

help:
	@echo "up      - the whole system in Docker (API, workers, replay, web)"
	@echo "down    - stop it"
	@echo "data    - download StatsBomb open data and build the full archive"
	@echo "seed    - load the archive into DynamoDB and MinIO"
	@echo "train   - rebuild the training set and the win-probability model"
	@echo "test    - the full backend test suite"
	@echo "lint    - ruff"
	@echo "types   - mypy --strict on the domain layer"
	@echo "bench   - measure everything the README claims"
	@echo "web     - run the web app against a local API"
	@echo "check   - lint, types, tests, web typecheck"
	@echo "free    - is the AWS account still free? (read-only)"

free:
	cd infra && python free_check.py

up:
	docker compose up -d --build
	@echo "Web http://localhost:5173  ·  API http://localhost:8080/docs"

down:
	docker compose down

logs:
	docker compose logs -f --tail 50

data:
	cd backend && python -m onside.ingest.build

seed:
	cd backend && python -m onside.ingest.seed

train:
	cd backend && python -m onside.models.dataset && python -m onside.models.train_wp

test:
	cd backend && python -m pytest tests -q

lint:
	cd backend && python -m ruff check onside tests benchmarks

types:
	cd backend && python -m mypy --strict onside/domain

bench:
	cd backend && python -m benchmarks.run_all

web:
	cd frontend && npm run dev

demo:
	cd backend && python -m onside.replay.export_demo && cd ../demo && python build.py

check: lint types test
	cd frontend && npm run typecheck

clean:
	docker compose down -v
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache frontend/dist
