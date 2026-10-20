from botocore.config import Config as BotocoreConfig
from strands import ModelRetryStrategy
from strands.models.bedrock import BedrockModel

from settings import SETTINGS


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(
        model_id=SETTINGS.model_id,
        max_tokens=SETTINGS.max_tokens,
        boto_client_config=BotocoreConfig(
            read_timeout=SETTINGS.bedrock_read_timeout,
            retries={"max_attempts": SETTINGS.bedrock_client_max_attempts, "mode": "standard"},
        ),
    )


def load_retry_strategy() -> ModelRetryStrategy:
    """Agent-level retries for Bedrock throttling, on top of the client's own retries."""
    return ModelRetryStrategy(
        max_attempts=SETTINGS.model_max_attempts,
        initial_delay=SETTINGS.model_retry_initial_delay,
        max_delay=SETTINGS.model_retry_max_delay,
    )
