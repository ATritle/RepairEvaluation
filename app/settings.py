"""Environment configuration (.env) - currently only the P21 connection."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    p21_server: str = "sql19"
    p21_database: str = "Prophet21"
    p21_user: str = ""
    p21_password: str = ""
    p21_driver: str = "ODBC Driver 17 for SQL Server"
    p21_company_id: str = ""  # optional filter, blank = all companies
    p21_timeout: int = 8

    @property
    def p21_configured(self) -> bool:
        return bool(self.p21_user and self.p21_password)

    @property
    def p21_connection_string(self) -> str:
        return (
            f"DRIVER={{{self.p21_driver}}};SERVER={self.p21_server};DATABASE={self.p21_database};"
            f"UID={self.p21_user};PWD={self.p21_password};"
            "TrustServerCertificate=yes;Encrypt=no;ApplicationIntent=ReadOnly"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
