FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    git bash curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    pytest \
    pytest-asyncio \
    pytest-cov \
    pytest-mock \
    requests \
    httpx \
    aiohttp \
    flask \
    django \
    fastapi \
    pydantic \
    sqlalchemy \
    alembic \
    redis \
    numpy \
    pandas \
    scipy \
    scikit-learn \
    matplotlib \
    click \
    typer \
    python-dotenv \
    pyyaml \
    jinja2 \
    faker \
    freezegun \
    responses

WORKDIR /tmp/repos
CMD ["sleep", "infinity"]