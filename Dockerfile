# GPU image based on CUDA + cuDNN. The defaults build the main image: CUDA 13.0 with torch
# 2.10.0+cu130, for current cards and the GB10. docker-compose.yml passes the five CUDA build args
# from .env, with these defaults repeated there (keep the two equal); a Pascal host such as one with
# a Tesla P40 (sm_61) sets them for CUDA 12.6 in its .env: CUDA 13 and the cu128/cu130 torch builds
# dropped sm_50-sm_61, and the cu126 build still carries sm_60 kernels, which run on sm_61.
# The five go together: the base image, its cuBLAS package, the torch build for that CUDA, and
# the kernels the build must carry.
ARG CUDA_IMAGE=nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04

# CTranslate2, which faster-whisper runs on, publishes CUDA builds for x86_64 against CUDA 12,
# with kernels from sm_53 up. `CTRANSLATE2=source` compiles it here instead, for the CUDA of
# CTRANSLATE2_BUILD_IMAGE (a -devel image of the same CUDA as CUDA_IMAGE) and the architectures
# in CTRANSLATE2_CUDA_ARCHES, plain numbers separated by spaces: that is how an aarch64 GB10
# (CUDA 13, 121) or a Maxwell Tesla M40 (CUDA 12.6, 52) gets a GPU build. The default, `wheel`,
# builds nothing and takes CTranslate2 from PyPI with faster-whisper. The flags are those of the
# project's own release builds, minus the x86-only CPU backends: no cuDNN (the convolutions use
# its own kernel, as in the PyPI wheels) and cuBLAS opened at runtime. BuildKit builds the source
# stage only when it is selected; the legacy builder builds every stage.
ARG CTRANSLATE2=wheel
ARG CTRANSLATE2_BUILD_IMAGE=nvidia/cuda:13.0.3-devel-ubuntu24.04
ARG CTRANSLATE2_VERSION=4.9.0
ARG CTRANSLATE2_CUDA_ARCHES=121
ARG FASTER_WHISPER=false

# Nothing to build: an empty /out, so that the runtime image copies the same path either way.
FROM ${CUDA_IMAGE} AS ctranslate2-wheel
RUN mkdir -p /out

FROM ${CTRANSLATE2_BUILD_IMAGE} AS ctranslate2-source
ARG CTRANSLATE2_VERSION
ARG CTRANSLATE2_CUDA_ARCHES
ARG FASTER_WHISPER
# Refused before half an hour of compiling rather than after it: the build is only for
# faster-whisper, and the wheel is installed under constraints.txt, which pins one version.
COPY constraints.txt /tmp/constraints.txt
RUN [ "$FASTER_WHISPER" = "true" ] \
        || { echo "CTRANSLATE2=source builds CTranslate2 for faster-whisper: set FASTER_WHISPER=true" >&2; exit 1; } \
    && grep -qx "ctranslate2==${CTRANSLATE2_VERSION}" /tmp/constraints.txt \
        || { echo "CTRANSLATE2_VERSION=${CTRANSLATE2_VERSION} is not the ctranslate2 pin in constraints.txt" >&2; exit 1; } \
    && for arch in ${CTRANSLATE2_CUDA_ARCHES}; do \
        case "$arch" in ''|*[!0-9]*) echo "CTRANSLATE2_CUDA_ARCHES takes numbers such as 52 or 121, not ${arch}" >&2; exit 1;; esac; \
    done
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        cmake \
        build-essential \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v${CTRANSLATE2_VERSION} --recurse-submodules --shallow-submodules \
        https://github.com/OpenNMT/CTranslate2.git /src
# Maxwell (sm_50, sm_52) has no f16x2 arithmetic, and one AWQ kernel uses it unguarded, so ptxas
# refuses the whole build for those targets; the patch traps in that kernel below sm_53 (see its
# header). Applied only when an architecture below 53 is asked for, so every other build is the
# upstream source unchanged.
COPY docker/ctranslate2-sm52.patch /tmp/ctranslate2-sm52.patch
RUN for arch in ${CTRANSLATE2_CUDA_ARCHES}; do \
        if [ "$arch" -lt 53 ]; then git -C /src apply /tmp/ctranslate2-sm52.patch || exit 1; break; fi; \
    done
WORKDIR /src/build
# CMake takes the architectures as a semicolon list; the arg is space-separated for the loops here.
RUN cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_CLI=OFF \
        -DWITH_MKL=OFF -DWITH_RUY=ON -DOPENMP_RUNTIME=COMP \
        -DWITH_CUDA=ON -DWITH_CUDNN=OFF -DCUDA_DYNAMIC_LOADING=ON \
        -DCMAKE_CUDA_ARCHITECTURES="$(echo ${CTRANSLATE2_CUDA_ARCHES} | tr ' ' ';')" \
        -DCMAKE_CUDA_FLAGS="-Xfatbin=-compress-all" \
    && make -j"$(nproc)" install
# Kernels for every requested architecture, or the build is refused: one missing would build
# fine and fail on the first model load with "no kernel image is available".
RUN for arch in ${CTRANSLATE2_CUDA_ARCHES}; do \
        cuobjdump --list-elf /usr/local/lib/libctranslate2.so | grep -q "\.sm_${arch}\.cubin$" \
            || { echo "libctranslate2 carries no sm_${arch} kernels" >&2; exit 1; }; \
    done
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /src/python/install_requirements.txt \
    && cd /src/python && /venv/bin/python setup.py bdist_wheel -d /out/wheel
# The cuBLAS this build opens at runtime, by soname, for the runtime image to check.
RUN mkdir -p /out/lib && cp -a /usr/local/lib/libctranslate2.so* /out/lib/ \
    && grep -ao 'libcublas\.so\.[0-9]*' /usr/local/lib/libctranslate2.so | head -1 > /out/cublas-soname \
    && test -s /out/cublas-soname

FROM ctranslate2-${CTRANSLATE2} AS ctranslate2

FROM ${CUDA_IMAGE}

# ffmpeg is required by pydub; libsndfile1 is required by soundfile.
# The cuBLAS package provides the cuBLAS / cuBLASLt runtime that torch calls into
# (cublasLtMatmul*). The `-runtime` base image does not include it by default -
# without it the first matmul on CUDA fails with `CUBLAS_STATUS_NOT_INITIALIZED`.
# It must match the CUDA of the base image: libcublas-13-0 for 13.0, libcublas-12-6 for 12.6.
ARG CUBLAS_PACKAGE=libcublas-13-0
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        ffmpeg \
        build-essential \
        libsndfile1 \
        ${CUBLAS_PACKAGE} \
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
ARG TORCH_VERSION=2.10.0
ARG TORCH_CUDA=cu130
RUN uv pip install --no-cache \
        --extra-index-url https://download.pytorch.org/whl/${TORCH_CUDA} \
        torch==${TORCH_VERSION}+${TORCH_CUDA} torchaudio==${TORCH_VERSION}+${TORCH_CUDA}

COPY requirements.txt constraints.txt /opt/
RUN uv pip install --no-cache -r requirements.txt -c constraints.txt

# Parakeet is opt-in at build time too: `--build-arg PARAKEET=true`. It and the diarizer share
# one transformers release, which carries both architectures; the assertions below check it.
ARG PARAKEET=false
COPY requirements-parakeet.txt /opt/requirements-parakeet.txt
RUN if [ "$PARAKEET" = "true" ]; then uv pip install --no-cache -r requirements-parakeet.txt -c constraints.txt; fi

# faster-whisper is opt-in at build time too: `--build-arg FASTER_WHISPER=true`. CTranslate2's
# PyPI wheels have CUDA builds for x86_64 only, made against CUDA 12 and cuDNN 9, so with them the
# image must be a CUDA 12 build of the five args above. With CTRANSLATE2=source the library built
# above is installed first, and the PyPI wheel is never fetched: the constraint pins the version
# that was built. The checks below refuse anything else.
ARG FASTER_WHISPER=false
COPY --from=ctranslate2 /out /opt/ctranslate2
COPY requirements-faster-whisper.txt /opt/requirements-faster-whisper.txt
RUN if [ "$FASTER_WHISPER" = "true" ]; then \
        if [ -d /opt/ctranslate2/wheel ]; then \
            cp -a /opt/ctranslate2/lib/. /usr/local/lib/ && ldconfig \
            && uv pip install --no-cache /opt/ctranslate2/wheel/*.whl -c constraints.txt; \
        fi \
        && uv pip install --no-cache -r requirements-faster-whisper.txt -c constraints.txt; \
    fi

# Speaker diarization is opt-in at build time: `--build-arg DIARIZE=true`. Off, the image is
# what it was before diarization existed.
ARG DIARIZE=false
COPY requirements-diarize.txt /opt/requirements-diarize.txt
RUN if [ "$DIARIZE" = "true" ]; then uv pip install --no-cache -r requirements-diarize.txt -c constraints.txt; fi

# The torch wheel above is a CUDA build chosen on purpose, and the resolutions that follow it
# are unconstrained: anything depending on torch can replace it, and the failure surfaces much
# later as cuBLAS and cuDNN errors that read like a driver problem. Fail the build instead.
RUN python3 -c "import torch; v = torch.__version__; assert '+${TORCH_CUDA}' in v, f'torch was replaced by {v}'"

# The build must carry kernels for the target card; any one of TORCH_ARCHES will do. NVIDIA GB10
# (DGX Spark) is sm_121 and the cu130 build carries no sm_121 kernels: it runs on the sm_120 ones
# and the compute_120 PTX. A Tesla P40 is sm_61 and runs on the sm_60 kernels of the cu126 build.
# Checked from the compiled flags, because get_arch_list() reads empty without a GPU at build
# time. A torch that drops them all would build fine and fail on the first CUDA call.
ARG TORCH_ARCHES="sm_121 sm_120 compute_120"
RUN python3 -c "import torch; flags = torch._C._cuda_getArchFlags().split(); wanted = '${TORCH_ARCHES}'.split(); \
assert any(arch in flags for arch in wanted), f'no kernels for {wanted}: {flags}'"
RUN if [ "$DIARIZE" = "true" ]; then \
        python3 -c "from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES; \
assert 'nemotron3_diarization' in CONFIG_MAPPING_NAMES, 'this transformers build does not carry the diarization model'"; \
    fi
# CTranslate2 opens cuBLAS (and, from PyPI, cuDNN 9) only when the first model loads, so a
# mismatched image would build and then fail at startup. Fail the build instead: dlopen needs no
# GPU. From PyPI, that is cuBLAS 12 and cuDNN 9 on x86_64. Built from source, it is the cuBLAS the
# build recorded, and the library Python loads must be that build and not a PyPI wheel's copy.
RUN if [ "$FASTER_WHISPER" = "true" ] && [ -s /opt/ctranslate2/cublas-soname ]; then \
        python3 -c "import ctypes, faster_whisper, ctranslate2; \
ctypes.CDLL(open('/opt/ctranslate2/cublas-soname').read().strip()); \
maps = open('/proc/self/maps').read(); \
assert '/usr/local/lib/libctranslate2.so' in maps, 'CTranslate2 is not the source build'"; \
    elif [ "$FASTER_WHISPER" = "true" ]; then \
        python3 -c "import ctypes, platform, faster_whisper; \
assert platform.machine() == 'x86_64', 'CTranslate2 has CUDA builds for x86_64 only; build it with CTRANSLATE2=source'; \
ctypes.CDLL('libcublas.so.12'); ctypes.CDLL('libcudnn.so.9')"; \
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
# Only the directories the server writes. A recursive chown of /opt rewrote the whole venv into
# a layer of its own and doubled the image (6.7 GB more); the server only reads the venv.
RUN chown stt:stt /opt /opt/models /opt/logs /opt/recs

# Start as root: the entrypoint chowns the bind-mounted dirs (the build-time
# chown above cannot reach host-owned mounts) and drops privileges to stt.
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]

# A container must listen on every interface: the server's own default is loopback.
ENV STT_HOST=0.0.0.0

EXPOSE 5051
CMD ["python3", "stt_server.py"]
