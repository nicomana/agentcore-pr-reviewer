import os

from strands.models.bedrock import BedrockModel

DEFAULT_MODEL_ID = "us.anthropic.claude-opus-5-5"


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(
        model_id=os.getenv("MODEL_ID", DEFAULT_MODEL_ID),
        max_tokens=32000,
    )
