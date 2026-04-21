# GPU image based on CUDA 13.2 + cuDNN.
FROM nvidia/cuda:13.2.1-cudnn-runtime-ubuntu24.04

# ffmpeg is required by pydub; libsndfile1 is required by soundfile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        libsndfile1 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

ENV PATH="/opt/venv/bin:${PATH}"

RUN python3 -m venv "/opt/venv" \
 && pip install --no-cache-dir --upgrade pip

COPY requirements.txt /opt/requirements.txt
# Install GPU-accelerated PyTorch and other dependencies.
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.10.0+cu130 torchaudio==2.10.0+cu130 \
 && pip install --no-cache-dir -r requirements.txt

COPY stt_server.py /opt/stt_server.py
COPY stt_client.py /opt/stt_client.py
RUN mkdir -p /opt/libs && touch /opt/libs/__init__.py
RUN mkdir -p /opt/models /opt/logs /opt/recs

RUN useradd --no-create-home --shell /bin/false stt
RUN chown -R stt:stt /opt
USER stt

EXPOSE 5099
CMD ["python3", "stt_server.py"]

