from openaleph_procrastinate.settings import OpenAlephSettings
from pydantic_settings import SettingsConfigDict
from servicelayer import settings as sls


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


_settings = OpenAlephSettings()

# Also store cached values in the SQL database
# Force psycopg3 for SQLAlchemy if fragments_uri is postgres
fragments_uri = _settings.fragments_uri
if fragments_uri and fragments_uri.startswith("postgresql://"):
    fragments_uri = fragments_uri.replace("postgresql://", "postgresql+psycopg://", 1)
sls.TAGS_DATABASE_URI = fragments_uri
