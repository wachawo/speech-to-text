SHELL := /bin/zsh

VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
GUNICORN := $(VENV_DIR)/bin/gunicorn

.PHONY: install start run stop gunicorn

install:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "[install] Creating virtual environment in $(VENV_DIR)"; \
		python3 -m venv "$(VENV_DIR)"; \
	else \
		echo "[install] Virtual environment already exists: $(VENV_DIR)"; \
	fi
	@echo "[install] Installing Ubuntu packages (ffmpeg, build-essential, libsndfile1)"
	sudo apt-get update
	sudo apt-get install -y ffmpeg build-essential libsndfile1 python3-venv
	@echo "[install] Installing Python dependencies from requirements.txt"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "[run] Missing virtual environment. Run: make install"; \
		exit 1; \
	fi
	$(PYTHON) stt_server.py

gunicorn:
	@if [ ! -x "$(GUNICORN)" ]; then \
		echo "[gunicorn] Missing virtual environment. Run: make install"; \
		exit 1; \
	fi
	$(GUNICORN) --config gu.py stt_server:app

start:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "[start] Missing virtual environment. Run: make install"; \
		exit 1; \
	fi
	@if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		echo "[start] Server already running with PID $$(cat $(PID_FILE))"; \
		exit 0; \
	fi
	@mkdir -p logs
	@nohup "$(PYTHON)" stt_server.py > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@echo "[start] Server started in background (PID $$(cat $(PID_FILE)))"
	@echo "[start] Logs: $(LOG_FILE)"

stop:
	@if [ ! -f "$(PID_FILE)" ]; then \
		echo "[stop] PID file not found; server is probably not running"; \
		exit 0; \
	else \
		PID="$$(cat $(PID_FILE))"; \
		if kill -0 "$$PID" 2>/dev/null; then \
			echo "[stop] Stopping server PID $$PID"; \
			kill "$$PID"; \
			sleep 1; \
			if kill -0 "$$PID" 2>/dev/null; then \
				echo "[stop] PID $$PID still alive; sending SIGKILL"; \
				kill -9 "$$PID"; \
			fi; \
			rm -f "$(PID_FILE)"; \
			echo "[stop] Server stopped"; \
		else \
			echo "[stop] Stale PID file found; cleaning up"; \
			rm -f "$(PID_FILE)"; \
		fi; \
	fi

