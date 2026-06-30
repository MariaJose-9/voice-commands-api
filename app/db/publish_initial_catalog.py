"""CLI helper to publish the initial catalog after seeding."""

from __future__ import annotations

import json
from typing import Any

from app.db.session import Session as DBSession, engine
from app.services.publish_service import publish_catalog


def publish_initial_catalog() -> dict[str, Any]:
    """Publish the current seeded catalog as the active runtime version."""

    if DBSession is None or engine is None:
        raise RuntimeError("Database dependencies are not installed.")

    with DBSession(engine) as session:
        return publish_catalog(session, actor_user_id=None)


def main() -> None:
    """CLI entry point for `python -m app.db.publish_initial_catalog`."""

    result = publish_initial_catalog()
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
