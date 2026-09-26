# GPU image based on CUDA 13.0 + cuDNN.
FROM nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04

# ffmpeg is required by pydub; libsndfile1 is required by soundfile.
# libcublas-13-0 provides cuBLAS / cuBLASLt runtime that torch 2.10+cu130
# calls into (cublasLtMatmul*). The `-runtime` base image does not include
# it by default - without this package the first matmul on CUDA fails with
# `CUBLAS_STATUS_NOT_INITIALIZED`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        ffmpeg \
        build-essential \
        libsndfile1 \
        libcublas-13-0 \
    && rm -rf /var/lib/apt/lists/*

# uv: fast Python package installer (https://github.com/astral-sh/uv).
# Pinned, not :latest - when the tag moved, every layer after this one missed the cache and
# the build re-downloaded torch and the CUDA wheels (20 minutes on the deployment host).
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/

WORKDIR /opt

ENV PATH="/opt/venv/bin:${PATH}"
ENV UV_LINK_MODE=copy

RUN uv venv /opt/venv --python python3

# The CUDA wheels run to about 2.5 GB, and on a slow link uv's default 30 s read timeout has
# failed a build here partway through them.
ENV UV_HTTP_TIMEOUT=300

# PyTorch in a layer of its own, ahead of requirements.txt. When both were one RUN after the
# COPY, editing a comment in requirements.txt threw away the cached CUDA wheels and sent the
# next build back to the network for all of them.
RUN uv pip install --no-cache \
        --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.10.0+cu130 torchaudio==2.10.0+cu130

COPY requirements.txt constraints.txt /opt/
RUN uv pip install --no-cache -r requirements.txt -c constraints.txt

# Parakeet is opt-in at build time too, and needs no git: it ships in released transformers.
# It is installed BEFORE the diarizer on purpose. Parakeet asks for transformers>=5.17.0 and the
# diarizer pins a 5.18.0.dev0 commit; whether a resolver keeps an installed pre-release against
# a plain `>=` is its own business, so the git pin simply goes last and always wins. That
# commit carries both architectures, and the assertions below check it.
ARG PARAKEET=false
COPY requirements-parakeet.txt /opt/requirements-parakeet.txt
RUN if [ "$PARAKEET" = "true" ]; then uv pip install --no-cache -r requirements-parakeet.txt -c constraints.txt; fi

# Speaker diarization is opt-in at build time: `--build-arg DIARIZE=true`. Off, the image is
# what it was before diarization existed.
ARG DIARIZE=false
COPY requirements-diarize.txt /opt/requirements-diarize.txt
# git is here only because the transformers pin is a git+https ref: uv shells out to the git
# binary and does not vendor one, and this base image has none. It is purged in the same layer
# so it never reaches the running image, and it can go entirely once the pin is a version.
RUN if [ "$DIARIZE" = "true" ]; then \
        apt-get update \
     && apt-get install -y --no-install-recommends git \
     && uv pip install --no-cache -r requirements-diarize.txt -c constraints.txt \
     && apt-get purge -y git && apt-get autoremove -y \
     && rm -rf /var/lib/apt/lists/*; \
    fi

# The torch wheel above is a CUDA build chosen on purpose, and the resolutions that follow it
# are unconstrained: anything depending on torch can replace it, and the failure surfaces much
# later as cuBLAS and cuDNN errors that read like a driver problem. Fail the build instead.
RUN python3 -c "import torch; v = torch.__version__; assert '+cu130' in v, f'torch was replaced by {v}'"

# NVIDIA GB10 (DGX Spark) is sm_121 and this torch build carries no sm_121 kernels: it runs on the
# sm_120 ones and the compute_120 PTX. Checked from the compiled flags, because get_arch_list()
# reads empty without a GPU at build time. A torch that drops both would build fine and fail on
# the first CUDA call.
RUN python3 -c "import torch; flags = torch._C._cuda_getArchFlags().split(); \
assert 'sm_121' in flags or 'sm_120' in flags or 'compute_120' in flags, f'no kernels for GB10: {flags}'"
RUN if [ "$DIARIZE" = "true" ]; then \
        python3 -c "from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES; \
assert 'nemotron3_diarization' in CONFIG_MAPPING_NAMES, 'this transformers build does not carry the diarization model'"; \
    fi
RUN if [ "$PARAKEET" = "true" ]; then \
        python3 -c "from transformers import AutoModelForTDT; import transformers; \
assert 'parakeet_tdt' in transformers.models.auto.configuration_auto.CONFIG_MAPPING_NAMES, \
'this transformers build does not carry the parakeet model'"; \
    fi

# The stt user is created with --no-create-home and only the bind-mounted dirs are chowned,
# so anything HuggingFace writes outside them fails. cache_dir covers the snapshot; HF_HOME
# covers the rest, including the Xet chunk cache.
ENV HF_HOME=/opt/models/hf

COPY stt_server.py stt_client.py gu.py /opt/
COPY libs /opt/libs
RUN mkdir -p /opt/models /opt/logs /opt/recs

# The server may run as a host uid (STT_UID) that owns nothing in the image and whose $HOME is
# /root. numba, which librosa uses, caches its compiled functions next to the package or under
# $HOME and refuses to import without somewhere to write ("cannot cache function ... no locator
# available"), which took the diarizer down; everything else that caches goes under XDG too.
ENV NUMBA_CACHE_DIR=/tmp/numba XDG_CACHE_HOME=/tmp/cache

RUN useradd --no-create-home --shell /bin/false stt
RUN chown -R stt:stt /opt

# Start as root: the entrypoint chowns the bind-mounted dirs (the build-time
# chown above cannot reach host-owned mounts) and drops privileges to stt.
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]

EXPOSE 5099
CMD ["python3", "stt_server.py"]
