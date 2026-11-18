from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    keitaro_url: AnyHttpUrl
    keitaro_api_key: SecretStr
    database_url: str = "sqlite:///./adrobot.db"
