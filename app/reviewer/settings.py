"""Runtime settings, read from environment variables.

Deployed values come from configs/<env>.yaml via infra/agent.yaml; the defaults here apply to local runs.
"""

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    # Model
    model_id: str = os.getenv("MODEL_ID", "us.anthropic.claude-opus-5-5")
    max_tokens: int = _int("MAX_TOKENS", 32000)
    # Agent-level retries on Bedrock throttling (Strands ModelRetryStrategy)
    model_max_attempts: int = _int("MODEL_MAX_ATTEMPTS", 6)
    model_retry_initial_delay: int = _int("MODEL_RETRY_INITIAL_DELAY", 4)
    model_retry_max_delay: int = _int("MODEL_RETRY_MAX_DELAY", 240)
    # Bedrock client (botocore) retries and read timeout per request
    bedrock_client_max_attempts: int = _int("BEDROCK_CLIENT_MAX_ATTEMPTS", 3)
    bedrock_read_timeout: int = _int("BEDROCK_READ_TIMEOUT", 120)
    # GitHub API
    github_credential_name: str = os.getenv("GITHUB_CREDENTIAL_NAME", "github")
    github_timeout: float = _float("GITHUB_TIMEOUT", 30)
    github_max_retries: int = _int("GITHUB_MAX_RETRIES", 4)
    github_retry_backoff: float = _float("GITHUB_RETRY_BACKOFF", 1.0)
    # How much the agent reads
    max_file_lines: int = _int("MAX_FILE_LINES", 800)
    max_description_chars: int = _int("MAX_DESCRIPTION_CHARS", 6000)


SETTINGS = Settings()
