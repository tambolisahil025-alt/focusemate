from pydantic_settings import BaseSettings

def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url

class Settings(BaseSettings):
    PROJECT_NAME: str = "FocuseMate API"
    
    DATABASE_URL: str = "postgresql+asyncpg://easy_user:xpjdul2WDIpd6EgeiUfMjj4JjaL5f2D2@dpg-d8cia0t8nd3s73cmcvm0-a/easy_database"
    
    SECRET_KEY: str = "generate_a_super_secret_random_string_here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    SERVER_PROTOCOL: str = "http"
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8000
    PORT: int | None = None
    BASE_API_URL: str | None = None
    CORS_ORIGINS: str = "*"
    
    # AI Assistant Configuration
    GROQ_API_KEY: str | None = None

    class Config:
        env_file = ".env"

    @property
    def api_base_url(self) -> str:
        if self.BASE_API_URL:
            return self.BASE_API_URL.rstrip("/")
        return f"{self.SERVER_PROTOCOL}://{self.SERVER_HOST}:{self.port}"

    @property
    def database_url(self) -> str:
        return normalize_database_url(self.DATABASE_URL)

    @property
    def port(self) -> int:
        return self.PORT or self.SERVER_PORT

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip().rstrip("/") for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()
