.PHONY: run test lint clean

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	python -m pytest tests/ -q

lint:
	python -m compileall -q app tests

clean:
	rm -f reprokit.db reprokit.db-wal reprokit.db-shm
	find . -name __pycache__ -type d -exec rm -rf {} +
