FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    git bash curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    pytest pytest-asyncio pytest-cov \
    requests urllib3 certifi idna charset-normalizer \
    flask django fastapi pydantic \
    numpy pandas

WORKDIR /tmp/repos
CMD ["sleep", "infinity"]