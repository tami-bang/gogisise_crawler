import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Configurations
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    
    # NestJS Backend Integration
    # Inside docker network, backend container can be accessed via http://backend:8000
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "gogisise_super_secret_internal_key_2026")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
