FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libglib2.0-0 \
    libegl1 \
    libopengl0 \
    libgl1 \
    libxkbcommon0 \
    libdbus-1-3 \
    libfontconfig1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-shape0 \
    libwayland-client0 \
    libwayland-cursor0 \
    libwayland-egl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY setup.py .
RUN pip install --no-cache-dir --break-system-packages -e .

COPY s7k_parser.py .
COPY viewer.py .

ENTRYPOINT ["seasonic"]
