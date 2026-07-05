import logging

from sqlalchemy import select, or_

from pica.database import Image, SimilarGroup, ImageStatus
from pica.utils import hamming_distance

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 10


def assign_similar_group(session, img: Image):
    """Find existing pending images with similar phash and assign to same group."""
    if not img.phash:
        return

    similar = session.execute(
        select(Image).where(
            Image.id != img.id,
            Image.phash.isnot(None),
            Image.status == ImageStatus.PENDING,
        )
    ).scalars().all()

    best_match = None
    best_dist = SIMILARITY_THRESHOLD + 1

    for other in similar:
        dist = hamming_distance(img.phash, other.phash)
        if dist < best_dist:
            best_dist = dist
            best_match = other

    if best_match is not None and best_match.similar_group_id is not None:
        img.similar_group_id = best_match.similar_group_id
        logger.info("added to existing group %d (distance=%d)", img.similar_group_id, best_dist)
    elif best_match is not None:
        group = SimilarGroup(
            name=f"相近组 #{best_match.id}",
            phash_ref=img.phash,
        )
        session.add(group)
        session.flush()
        best_match.similar_group_id = group.id
        img.similar_group_id = group.id
        logger.info("created group %d (distance=%d)", group.id, best_dist)
