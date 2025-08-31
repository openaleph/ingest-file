from rigour.mime import MIMEType, mimetype_extension, parse_mimetype
from servicelayer.extensions import get_extensions


def make_mtype(m: MIMEType) -> dict[str, str | None]:
    ext = mimetype_extension(m.name) or ""
    if ext:
        ext = f".{ext}"
    return {"label": m.label, "name": m.name, "ext": ext}


def define_env(env):
    """
    This is the hook for the variables, macros and filters.
    """
    extensions = get_extensions("ingestors")
    mimetypes = set()
    for cls in extensions:
        if cls.__name__ != "IgnoreIngestor":
            mimetypes.update(map(parse_mimetype, cls.MIME_TYPES))

    env.variables["ingestors"] = extensions
    env.variables["mimetypes"] = map(make_mtype, mimetypes)
