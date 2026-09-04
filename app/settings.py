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

    # Forge (app storage)
    forge_server: str = "sql19"
    forge_database: str = "Forge"
    forge_schema: str = "RepairEval"
    forge_user: str = ""
    forge_password: str = ""
    forge_driver: str = "ODBC Driver 17 for SQL Server"
    forge_timeout: int = 10

    # Photo bytes: "fs" = files under photo_fs_root (local folder now, UNC share
    # later), "db" = VARBINARY in Forge.RepairEval.photo_file. Metadata is always in Forge.
    photo_store: str = "fs"
    photo_fs_root: str = "data/photo_store"

    @property
    def forge_configured(self) -> bool:
        return bool(self.forge_user and self.forge_password)

    @property
    def forge_connection_string(self) -> str:
        return (
            f"DRIVER={{{self.forge_driver}}};SERVER={self.forge_server};DATABASE={self.forge_database};"
            f"UID={self.forge_user};PWD={self.forge_password};TrustServerCertificate=yes;Encrypt=no"
        )

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
