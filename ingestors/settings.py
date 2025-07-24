from openaleph_procrastinate.settings import OpenAlephSettings
from pydantic_settings import SettingsConfigDict
from servicelayer import env
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


settings = Settings()

# Also store cached values in the SQL database
sls.TAGS_DATABASE_URI = env.get("FTM_STORE_URI", env.get("ALEPH_DATABASE_URI"))

# ProcessingException is thrown whenever something goes wrong with
# parsing a file. Enable this with care, it can easily eat up the
# Sentry quota of events.
SENTRY_CAPTURE_PROCESSING_EXCEPTIONS = env.to_bool(
    "SENTRY_CAPTURE_PROCESSING_EXCEPTIONS", False
)
