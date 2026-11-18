SHELL := /bin/bash

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
# A pin the image does not carry is kept: faster-whisper exists only in builds that asked for it,
# and refreezing from any other image must not drop its versions. A package installed from a local
# file (CTranslate2 built with CTRANSLATE2=source) freezes as `name @ file:///...`, a path no other
# build has; it is left out, so its existing `name==version` pin is kept.
constraints:
	@docker run --rm --entrypoint uv stt_server_gpu:latest pip freeze --python /opt/venv/bin/python \
		| grep -viE '^(torch|torchaudio|triton|nvidia-|cuda-)' | grep -v ' @ file:' > constraints.txt.fresh
	@tail -n +10 constraints.txt | grep -viE "^($$(cut -d= -f1 constraints.txt.fresh | paste -sd'|'))==" \
		| cat - constraints.txt.fresh | sort -f -t= -k1,1 > constraints.txt.body
	@head -n 9 constraints.txt | cat - constraints.txt.body > constraints.txt.new
	@mv constraints.txt.new constraints.txt
	@rm -f constraints.txt.fresh constraints.txt.body
	@echo "[constraints] $$(grep -vc '^#' constraints.txt) packages frozen"

# Tag both running images as rollback-<current commit> before a deploy replaces them.
tag-rollback:
	@rev="$$(git rev-parse --short HEAD)"; \
	docker tag stt_server_gpu:latest "stt_server_gpu:rollback-$$rev" && \
	docker tag stt_www:latest "stt_www:rollback-$$rev" && \
	echo "[tag-rollback] stt_server_gpu:rollback-$$rev stt_www:rollback-$$rev"
