FROM node:20-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV NVM_DIR=/root/.nvm

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-pip jq curl ca-certificates ripgrep tmux asciinema tzdata \
    && curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" && nvm install 22 \
    && npm install -g @openai/codex@latest \
    && CODEX_BIN="$(readlink -f "$(command -v codex)")" \
    && ln -sf "$CODEX_BIN" /usr/local/bin/codex \
    && python3 -m pip install --break-system-packages --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY rollup /workspace/rollup
COPY scripts/ /usr/local/bin/

RUN chmod +x /usr/local/bin/* \
    && cd /workspace/rollup \
    && npm ci \
    && /usr/local/bin/reset-rollup-runtime

CMD ["/bin/bash"]
