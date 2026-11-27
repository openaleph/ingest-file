ENCRYPTED_MSG = (
    "The document might be protected with a password. Try removing the "
    "password protection and re-uploading the documents."
)
EMPTY_MSG = "The source file is empty (0 bytes) and has no content to extract."
EMPTY_SHEET_MSG = "This sheet is empty."


class ProcessingException(Exception):
    "A data-related error occurring during file processing."

    pass


class UnauthorizedError(Exception):
    """Raised when a document is protected by a password and can not be parsed."""

    pass
