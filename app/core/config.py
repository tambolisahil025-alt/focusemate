from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "FocuseMate API"
    
    DATABASE_URL: str = "postgresql+psycopg2://postgres:Admin@localhost:5432/focusemate"
    
    SECRET_KEY: str = "generate_a_super_secret_random_string_here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    SERVER_PROTOCOL: str = "http"
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8000
    BASE_API_URL: str | None = None

    class Config:
        env_file = ".env"

    @property
    def api_base_url(self) -> str:
        if self.BASE_API_URL:
            return self.BASE_API_URL
        return f"{self.SERVER_PROTOCOL}://{self.SERVER_HOST}:{self.SERVER_PORT}"

settings = Settings()
