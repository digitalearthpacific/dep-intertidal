
ARG BUILDPLATFORM="linux/amd64"
FROM --platform=${BUILDPLATFORM} ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV USE_PYGEOS=0

ADD src /app
ADD pyproject.toml /app/
WORKDIR /app

RUN echo 'deb http://deb.debian.org/debian/ unstable main contrib non-free' >> /etc/apt/sources.list
RUN apt-get update && apt-get upgrade -y
RUN apt install -y -t unstable gdal-bin
RUN apt-get install -y git libpq-dev libgdal-dev gdal-bin build-essential
RUN apt-get autoclean -y && apt-get autoremove -y && rm -rf /var/lib/{apt,dpkg,cache,log}

RUN uv sync --compile-bytecode

# Package FESS2022 Pacific Tidal Model In Build Process
RUN uv run python -c "from util import *; setup_tidal_models()"

#CMD ["uv", "run", "run.py"]


