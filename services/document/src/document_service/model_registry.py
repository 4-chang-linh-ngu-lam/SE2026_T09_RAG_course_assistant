from document_service.db import Base


def load_metadata():
    from document_service import models  # noqa: F401

    return Base.metadata
