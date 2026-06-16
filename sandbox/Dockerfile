FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    git bash curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install pytest pytest-asyncio

WORKDIR /tmp/repos
CMD ["sleep", "infinity"]