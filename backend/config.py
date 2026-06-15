# contains the keys and stuff

import os

from dotenv import load_dotenv

load_dotenv()

# llm
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# github
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
# postgres
DATABASE_URL = os.environ["DATABASE_URL"]
# redis
REDIS_URL = os.environ["REDIS_URL"]
# app
REPOS_DIR = os.environ.get("REPOS_DIR", "/tmp/repos")
# sandbox
SANDBOX_CONTAINER  = os.environ.get("SANDBOX_CONTAINER", "legacy-mod-agent-sandbox")