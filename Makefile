.PHONY: help setup run clean

help:
	@echo "Commands: make setup, make run, make clean"

setup:
	pip install -e .

run:
	sudo ztgateway --interface all --port 67

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete