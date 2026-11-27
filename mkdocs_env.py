import typer
from rigour.mime import MIMEType, mimetype_extension, parse_mimetype
from servicelayer.extensions import get_extensions
from typer.cli import get_docs_for_click


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

    env.variables["ingestors"] = sorted(extensions, key=lambda c: c.__name__)
    env.variables["mimetypes"] = sorted(
        map(make_mtype, mimetypes), key=lambda m: m["name"]
    )

    @env.macro
    def cli_reference() -> str:
        """Markdown reference for the `ingestors` command line, as `typer utils docs`"""
        from ingestors.cli import cli

        command = typer.main.get_command(cli)
        with typer.Context(command) as ctx:
            return get_docs_for_click(obj=command, ctx=ctx, name="ingestors")
