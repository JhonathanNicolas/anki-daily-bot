VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest
RUFF = $(VENV)/bin/ruff
VENV_SITE = $(VENV)/lib/python3.12/site-packages

.PHONY: install test lint run run-dry bot daily data schedule-install schedule-remove

install:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

test:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m pytest tests/ -v

lint:
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

run:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m src.main --all

run-dry:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m src.main --all --dry-run

bot:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m src.bot_runner

daily:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m src.scheduler

data:
	PYTHONPATH="$(VENV_SITE):$$PYTHONPATH" $(PYTHON) -m src.data_processor

# Install a daily cron job at 07:00 (edit SCHEDULE_HOUR to change)
SCHEDULE_HOUR ?= 7
CRON_CMD = cd $(shell pwd) && PYTHONPATH="$(VENV_SITE):$$PATH" $(shell pwd)/$(PYTHON) -m src.scheduler >> logs/scheduler.log 2>&1
schedule-install:
	(crontab -l 2>/dev/null | grep -v "src.scheduler"; echo "0 $(SCHEDULE_HOUR) * * * $(CRON_CMD)") | crontab -
	@echo "Cron job installed: daily at $(SCHEDULE_HOUR):00"

schedule-remove:
	crontab -l 2>/dev/null | grep -v "src.scheduler" | crontab -
	@echo "Cron job removed."
