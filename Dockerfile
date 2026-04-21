# GPU image based on CUDA 13.0 + cuDNN.
FROM nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04

# ffmpeg is required by pydub; libsndfile1 is required by soundfile.
# libcublas-13-0 provides cuBLAS / cuBLASLt runtime that torch 2.10+cu130
# calls into (cublasLtMatmul*). The `-runtime` base image does not include
# it by default — without this package the first matmul on CUDA fails with
# `CUBLAS_STATUS_NOT_INITIALIZED`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ffmpeg \
        build-essential \
        libsndfile1 \
        libcublas-13-0 \
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

