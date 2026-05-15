from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量与项目根目录的 .env 加载配置（启动 uvicorn 时 cwd 应为项目根）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None

    #: ``logging`` 级别名，如 ``INFO``、``DEBUG``。``DEBUG`` 会连带打开 LangChain / MCP / HTTP 等库的详细日志。
    log_level: str = "INFO"


settings = Settings()
