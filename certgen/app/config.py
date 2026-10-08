import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./certgen.db")
    cert_dir: str = os.getenv("CERT_DIR", "./generated_certificates")
    max_recipients: int = int(os.getenv("MAX_RECIPIENTS", "1000"))


settings = Settings()
