"""Explicit Core composition root for metadata consumers (Alembic/tools)."""

from app.common.db import Base


def load_metadata():
    from app.common import audit, outbox  # noqa: F401
    from app.modules.administration import models as administration  # noqa: F401
    from app.modules.classroom import models as classroom  # noqa: F401
    from app.modules.identity import models as identity  # noqa: F401
    from app.modules.notification import models as notification  # noqa: F401
    from app.modules.social.calendar import models as calendar  # noqa: F401
    from app.modules.social.comments import models as comments  # noqa: F401
    from app.modules.social.feed import models as feed  # noqa: F401

    return Base.metadata
