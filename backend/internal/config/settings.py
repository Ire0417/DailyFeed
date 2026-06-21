from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "DailyFeed"
    env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    postgres_user: str = "dailyfeed"
    postgres_password: str = "changeme"
    postgres_db: str = "dailyfeed"
    postgres_host: str = "db"
    postgres_port: int = 5432
    database_pool_size: int = 20
    database_max_overflow: int = 40

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me-please-in-production-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    # CORS —— 逗号分隔列表；设置为 "*" 则开放所有来源
    cors_origins: str = "*"

    # LLM summarization (可选，启用后使用 LLM 摘要，否则回退到抽取式)
    # provider: openai / deepseek / qwen
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_base_url: str | None = None   # 留空则使用各 provider 默认地址
    llm_model: str | None = None      # 留空则使用各 provider 默认模型
    llm_max_tokens: int = 600
    llm_max_chars: int = 12000
    llm_timeout_seconds: int = 60

    # Embedding（向量检索用，优先使用）
    # provider: openai / qwen  (qwen 走 dashscope compatible-mode)
    # 不配置时自动回退到 "伪哈希向量"（pseudo_hash），保证系统可启动并提供基本检索能力。
    embedding_provider: str = "qwen"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None     # 例如 text-embedding-v2
    embedding_timeout_seconds: int = 30

    # 向后兼容：若仅配置了 llm_api_key 而未单独配置 embedding，
    # 则复用 llm_api_key / llm_provider 作为 embedding 凭据（仅对 qwen/openai 生效）。
    @property
    def embedding_enabled(self) -> bool:
        return bool(self._resolved_embedding_api_key)

    @property
    def _resolved_embedding_api_key(self) -> str | None:
        return self.embedding_api_key or self.llm_api_key or self.openai_api_key

    @property
    def _resolved_embedding_provider(self) -> str:
        if self.embedding_provider:
            return self.embedding_provider
        if self.embedding_api_key and not self.llm_api_key:
            return self.llm_provider or "openai"
        return "qwen"

    @property
    def _resolved_embedding_base_url(self) -> str | None:
        if self.embedding_base_url:
            return self.embedding_base_url
        provider = self._resolved_embedding_provider
        if provider == "qwen":
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if provider == "openai":
            return "https://api.openai.com/v1"
        return None

    @property
    def _resolved_embedding_model(self) -> str | None:
        if self.embedding_model:
            return self.embedding_model
        if self._resolved_embedding_provider == "qwen":
            return "text-embedding-v2"
        return None

    # 向后兼容的 OpenAI 字段（仅当 llm_api_key 为空时生效）
    # 方便老用户无需改动配置就能继续用 OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_max_tokens: int = 2000

    # Agent
    agent_timeout_seconds: int = 600
    agent_max_retries: int = 3
    fetcher_concurrency: int = 5

    # Email
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@dailyfeed.com"
    smtp_use_tls: bool = True

    # Webhook
    wechat_webhook: str = ""
    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""

    # Schedule
    schedule_hour: int = 8
    schedule_minute: int = 0
    timezone: str = "Asia/Shanghai"
    fetch_window_hours: int = 24

    @property
    def database_url(self) -> str:
        # 本地开发模式：当数据库不可达时自动切换到 SQLite
        # 显式指定 database_url 时：直接使用即可（支持 sqlite:///./dailyfeed.db）
        if hasattr(self, "_database_url_raw") and self._database_url_raw:
            return self._database_url_raw
        # 环境变量覆盖：允许显式指定 sqlite://
        import os
        override = os.environ.get("DATABASE_URL")
        if override:
            return override
        # 正常：PostgreSQL
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def summary_enabled(self) -> bool:
        return self.llm_enabled

    @property
    def llm_enabled(self) -> bool:
        """若 llm_api_key 或 openai_api_key 非空，则启用 LLM 摘要。"""
        return bool(self.llm_api_key) or bool(self.openai_api_key)

    @property
    def _resolved_llm_api_key(self) -> str | None:
        return self.llm_api_key or self.openai_api_key

    @property
    def _resolved_llm_model(self) -> str | None:
        if self.llm_model:
            return self.llm_model
        if self.openai_api_key and not self.llm_api_key:
            return self.openai_model
        return None

    @property
    def _resolved_llm_provider(self) -> str:
        # 如果用户只填了旧的 openai_api_key，默认使用 openai provider
        if self.openai_api_key and not self.llm_api_key:
            return "openai"
        return self.llm_provider or "openai"


settings = Settings()
