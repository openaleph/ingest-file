from banal import ensure_list
from rigour.langs import iso_639_alpha3


def map_iso_languages(values) -> list[str]:
    """Map kreuzberg language values to ISO 639-3 codes accepted by FtM.

    kreuzberg reports declared languages as locales (e.g. "de-DE"), but FtM's
    `language` type only accepts bare ISO codes. Reduce each value to its
    primary subtag and resolve it to alpha-3 via rigour, dropping anything that
    does not map to a known language.
    """
    codes = []
    for value in ensure_list(values):
        if not value:
            continue
        primary = str(value).replace("_", "-").split("-")[0]
        code = iso_639_alpha3(primary)
        if code is not None:
            codes.append(code)
    return codes
