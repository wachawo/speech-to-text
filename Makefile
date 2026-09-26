SHELL := /bin/zsh

PID_FILE := .stt_server.pid
LOG_FILE := logs/stt_server.log

.PHONY: run start stop gunicorn test lint typecheck constraints tag-rollback

run:
	python3 stt_server.py

gunicorn:
	gunicorn --config gu.py stt_server:app

start:
	@if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		echo "[start] Server already running with PID $$(cat $(PID_FILE))"; \
		exit 0; \
	fi
	@mkdir -p logs
	@nohup python3 stt_server.py > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@echo "[start] Server started in background (PID $$(cat $(PID_FILE)))"
	@echo "[start] Logs: $(LOG_FILE)"

test:
	python3 -m pytest

lint:
	pre-commit run --all-files

typecheck:
	mypy

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

# Freeze what the verified GPU image resolved into constraints.txt (see the header of that file).
constraints:
	@head -n 9 constraints.txt > constraints.txt.new
	@docker run --rm --entrypoint uv stt_server_gpu:latest pip freeze --python /opt/venv/bin/python \
		| grep -viE '^(torch|torchaudio|triton|nvidia-|cuda-|transformers)' >> constraints.txt.new
	@mv constraints.txt.new constraints.txt
	@echo "[constraints] $$(grep -vc '^#' constraints.txt) packages frozen"

# Tag both running images as rollback-<current commit> before a deploy replaces them.
tag-rollback:
	@rev="$$(git rev-parse --short HEAD)"; \
	docker tag stt_server_gpu:latest "stt_server_gpu:rollback-$$rev" && \
	docker tag stt_www:latest "stt_www:rollback-$$rev" && \
	echo "[tag-rollback] stt_server_gpu:rollback-$$rev stt_www:rollback-$$rev"
