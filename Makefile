.PHONEY: help setup run clean

help:
	@echo "Commands: make setup, make run or make clean"

setup:
	pip install -r requirements.txt

run:
	sudo python3 /src/cli/main.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true