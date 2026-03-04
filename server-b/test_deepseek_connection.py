import json
import sys

from backend.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
)


def main() -> int:
    print("=== DeepSeek 连接测试（Server B）===")

    # 清理可能干扰的系统级代理，避免误用本地 127.0.0.1:7890 等无效代理
    import os as _os
    for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if _k in _os.environ:
            print(f"移除环境变量 {_k}={_os.environ[_k]!r}")
            _os.environ.pop(_k, None)
    print(f"BASE_URL = {DEEPSEEK_BASE_URL}")
    print(f"MODEL    = {DEEPSEEK_MODEL}")
    print(f"TIMEOUT  = {DEEPSEEK_TIMEOUT}s")
    print(f"API_KEY  前 8 位 = {DEEPSEEK_API_KEY[:8]!r}")

    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY 未配置，无法测试。")
        return 1

    try:
        from openai import OpenAI
    except Exception as e:  # pragma: no cover
        print("ERROR: 无法导入 openai 客户端，请先在 server-b 目录执行 `pip install -r requirements.txt`")
        print(f"detail: {e}")
        return 1

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        timeout=DEEPSEEK_TIMEOUT,
    )

    print("\n发送测试请求到 DeepSeek ...")
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个简洁的测试助手。"},
                {"role": "user", "content": "简单回复两个字：成功"},
            ],
            max_tokens=16,
            stream=False,
        )
    except Exception as e:
        print("\n=== 请求失败 ===")
        print(repr(e))
        return 1

    try:
        choice = resp.choices[0]
        content = choice.message.content
    except Exception:
        content = str(resp)

    print("\n=== 请求成功 ===")
    print("原始响应（裁剪后）：")
    try:
        print(json.dumps(resp.model_dump(), ensure_ascii=False)[:800])
    except Exception:
        print(str(resp)[:800])

    print("\n模型输出内容：")
    print(content)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

