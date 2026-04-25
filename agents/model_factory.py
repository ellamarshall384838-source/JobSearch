"""
Model creation and API validation helpers.
"""
import httpx
from openai import OpenAI, AuthenticationError, APIConnectionError, APIStatusError

from agentscope.model import OpenAIChatModel
from agentscope.formatter import OpenAIChatFormatter


def create_model(api_key: str, base_url: str, model_name: str) -> OpenAIChatModel:
    """Instantiate an agentscope OpenAIChatModel with the given credentials."""
    client_kwargs: dict = {"timeout": 90}
    if base_url and base_url.startswith(("http://", "https://")):
        client_kwargs["base_url"] = base_url
    return OpenAIChatModel(
        model_name=model_name,
        api_key=api_key,
        client_kwargs=client_kwargs,
    )


def get_formatter() -> OpenAIChatFormatter:
    return OpenAIChatFormatter()


def validate_api(
    api_key: str,
    base_url: str,
    model_name: str,
) -> tuple[bool, str]:
    """
    Quick connectivity check using a tiny chat completion.
    Returns (success, message).
    """
    try:
        kwargs: dict = {
            "api_key": api_key,
            "timeout": 20,
            "http_client": httpx.Client(trust_env=False, timeout=20),
        }
        if base_url and base_url.startswith(("http://", "https://")):
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        # Avoid max_tokens — newer models (o-series, gpt-5) reject it.
        # Just send a minimal request; we only care about the HTTP status.
        client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True, "API 连接成功！"
    except AuthenticationError:
        return False, "API Key 无效（401 Unauthorized）"
    except APIConnectionError as e:
        return False, f"连接失败，请检查网络或 Base URL：{e}"
    except APIStatusError as e:
        return False, f"API 状态异常 {e.status_code}：{e.message}"
    except Exception as e:
        return False, f"未知错误：{e}"
