from __future__ import annotations

import os

DEFAULT_MODEL = "gpt-5.5"


class OpenAIServiceError(RuntimeError):
    pass


def get_api_key(api_key: str | None = None) -> str:
    key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise OpenAIServiceError("缺少 OPENAI_API_KEY。请在页面中临时输入，或在系统环境变量中设置。")
    return key


def generate_text(
    prompt: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = 1600,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIServiceError("未安装 openai 包，请先运行 pip install -r requirements.txt。") from exc

    try:
        client = OpenAI(api_key=get_api_key(api_key))
        response = client.responses.create(
            model=model.strip() or DEFAULT_MODEL,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )
    except Exception as exc:
        raise OpenAIServiceError(f"OpenAI API 调用失败：{exc}") from exc

    output_text = getattr(response, "output_text", "") or ""
    if not output_text.strip():
        raise OpenAIServiceError("OpenAI API 返回为空，请稍后重试或检查模型权限。")
    return output_text.strip()

