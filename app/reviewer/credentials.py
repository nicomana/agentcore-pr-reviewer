import os

from bedrock_agentcore.identity.auth import requires_api_key

from settings import SETTINGS


@requires_api_key(provider_name=SETTINGS.github_credential_name)
def _agentcore_identity_api_key_provider(api_key: str) -> str:
    """Fetch the GitHub token from AgentCore Identity."""
    return api_key


def get_github_token() -> str:
    """GITHUB_TOKEN when running locally; AgentCore Identity when deployed."""
    return os.getenv("GITHUB_TOKEN") or _agentcore_identity_api_key_provider()
