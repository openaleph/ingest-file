from openaleph_procrastinate.settings import OpenAlephSettings
from pydantic_settings import SettingsConfigDict

OP_INGEST = "ingest"


class Settings(OpenAlephSettings):
    """
    `ingest-file` settings management using
    [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

    Note:
        All settings can be set via environment variables, prepending
        `INGESTORS_` (except for those with another alias) via runtime or in a
        `.env` file.
    """

    model_config = SettingsConfigDict(
        env_prefix="ingestors_",
        env_file=".env",
        extra="ignore",  # other envs in .env file
    )

    convert_timeout: int = 300
    """Headless libreoffice document convert timeout in seconds"""

    tika_fallback: bool = False
    """Use Apache Tika as a text extraction fallback"""

    calamine: bool = False
    """Use the Rust calamine implementation (python-calamine) for spreadsheets"""

    lakehouse_flush_size: int = 10_000
    """Size cap until when the journal should be flushed to parquet"""

    @property
    def tags_database_uri(self) -> str:
        """Resolve the tags database URI from fragments_uri, forcing psycopg3
        driver for PostgreSQL."""
        uri = self.fragments_uri
        if uri and uri.startswith("postgresql://"):
            uri = uri.replace("postgresql://", "postgresql+psycopg://", 1)
        return uri
