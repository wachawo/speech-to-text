# Base image (slim Python 3.11)
FROM python:3.11-slim

LABEL maintainer="you@example.com"
LABEL description="Whisper Speech-to-Text HTTP server (Flask + uvicorn)"

# System dependencies
# ffmpeg is required by pydub to decode mp3/ogg/m4a/etc.
# build-essential and libsndfile1 are needed for some audio/ML wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
WORKDIR /opt

COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY stt_server.py /opt/stt_server.py
COPY stt_client.py /opt/stt_client.py
# libs/stt.py is bind-mounted at runtime (see docker-compose.yml volumes)
# but we create the package directory so imports don't fail during build
RUN mkdir -p /opt/libs && touch /opt/libs/__init__.py

# Runtime directories (populated by volumes)
RUN mkdir -p /opt/models /opt/logs /opt/recs

# Unprivileged user
RUN useradd --no-create-home --shell /bin/false stt
RUN chown -R stt:stt /opt
USER stt

# Expose and run
EXPOSE 5099

# Production: uvicorn called from stt_server.main()
CMD ["python", "stt_server.py"]

