"""Server-only configuration; keys can be supplied through a private local file."""

import os
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def load_dify_key() -> str:
    """Read the API key without exposing it in logs or browser responses."""
    key = os.getenv("DIFY_API_KEY", "").strip()
    if key:
        return key
    path = Path(os.getenv("DIFY_API_KEY_FILE", "../../API/dify.txt"))
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return ""
    value = path.read_text(encoding="utf-8-sig").strip()
    if value.startswith("DIFY_API_KEY="):
        value = value.split("=", 1)[1].strip().strip("\"'")
    if "\n" in value or "\r" in value:
        raise ValueError("DIFY_API_KEY_FILE must contain one key, or one DIFY_API_KEY= line")
    return value


DIFY_API_KEY = load_dify_key()
DIFY_API_BASE_URL = os.getenv("DIFY_API_BASE_URL", "https://api.dify.ai/v1").rstrip("/")
JAVA_API_URL = os.getenv("JAVA_API_URL", "http://127.0.0.1:8080").rstrip("/")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")
COOKIE_SECURE = os.getenv("AI_COOKIE_SECURE", "false").lower() == "true"
MAX_STREAMS = max(1, min(128, int(os.getenv("AI_MAX_STREAMS", "16"))))


def local_redis_url() -> str:
    """Reuse the local Java Redis configuration without logging private values."""
    path = ROOT.parent / "src/main/resources/application-local.yml"
    if path.is_file() and JAVA_API_URL.startswith(("http://127.0.0.1:", "http://localhost:")):
        content = path.read_text(encoding="utf-8-sig")
        block = re.search(r"(?m)^    redis:\s*\r?\n((?:^      .*(?:\r?\n|$))*)", content)
        if block:
            values = dict(re.findall(r"(?m)^      (host|port|password|username|database):\s*([^\r\n#]*)", block[1]))
            values = {key: value.strip().strip("\"'") for key, value in values.items()}
            if any("${" in value for value in values.values()):
                raise ValueError("Set AI_REDIS_URL explicitly for environment-based Redis credentials")
            password = values.get("password", "")
            auth = f"{quote(values.get('username', ''), safe='')}:{quote(password, safe='')}@" if password else ""
            return f"redis://{auth}{values.get('host', '127.0.0.1')}:{values.get('port', '6379')}/{values.get('database', '0')}"
    return "redis://127.0.0.1:6379/0"


REDIS_URL = os.getenv("AI_REDIS_URL") or local_redis_url()
AUTH_REDIS_URL = os.getenv("AI_AUTH_REDIS_URL") or REDIS_URL
REDIS_PREFIX = os.getenv("AI_REDIS_PREFIX", "ai:gateway:")
