FROM python:3.12-slim

# Node.js is required because the GitHub MCP server is a Node package,
# launched as a subprocess by mcp_client.py
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @modelcontextprotocol/server-github

# Docker CLI is required so bash_server.py can run `docker exec`
# into the sandbox container from inside this container
RUN curl -fsSL https://get.docker.com | sh

RUN pip install uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .