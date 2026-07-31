"""Periodic retention maintenance for ephemeral research artifacts."""

import asyncio
import logging
from datetime import datetime, timezone

from app.db.database import SessionLocal
from app.db.models import NoteSource, WebSnapshot

logger = logging.getLogger(__name__)


def cleanup_expired_web_snapshots() -> int:
    with SessionLocal() as db:
        referenced = db.query(NoteSource.snapshot_id).filter(NoteSource.snapshot_id.is_not(None))
        snapshots = db.query(WebSnapshot).filter(
            WebSnapshot.is_pinned.is_(False),
            WebSnapshot.expires_at.is_not(None),
            WebSnapshot.expires_at < datetime.now(timezone.utc),
            ~WebSnapshot.id.in_(referenced),
        ).all()
        count = len(snapshots)
        for snapshot in snapshots:
            db.delete(snapshot)
        db.commit()
        return count


async def run_daily_maintenance() -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup_expired_web_snapshots)
        except Exception:
            logger.exception("Daily web snapshot cleanup failed")
        await asyncio.sleep(24 * 60 * 60)
