import logging
from collections import defaultdict

from sqlalchemy import select

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


def batch_assign_groups(session, images: list[Image]):
    """Assign groups for multiple images in one pass.

    Loads all existing pending images ONCE and compares all new images
    against them in memory, avoiding N repeated queries.
    """
    new_with_phash = [img for img in images if img.phash]
    if not new_with_phash:
        return

    # Load all existing pending images that have phash
    existing = session.execute(
        select(Image).where(
            Image.phash.isnot(None),
            Image.status == ImageStatus.PENDING,
            Image.id.notin_([img.id for img in new_with_phash]),
        )
    ).scalars().all()

    # Group existing images by group_id for quick lookup
    existing_by_group: dict[int | None, list[Image]] = defaultdict(list)
    for e in existing:
        existing_by_group[e.similar_group_id].append(e)

    # Track groups we've already used to avoid creating duplicates
    group_cache: dict[int | None, tuple[int | None, int]] = {}

    for img in new_with_phash:
        best_match = None
        best_dist = SIMILARITY_THRESHOLD + 1

        # Check existing images
        for e in existing:
            dist = hamming_distance(img.phash, e.phash)
            if dist < best_dist:
                best_dist = dist
                best_match = e

        if best_match is not None and best_match.similar_group_id is not None:
            img.similar_group_id = best_match.similar_group_id
            existing.append(img)
            existing_by_group[img.similar_group_id].append(img)
        elif best_match is not None:
            group = SimilarGroup(
                name=f"相近组 #{best_match.id}",
                phash_ref=img.phash,
            )
            session.add(group)
            session.flush()
            best_match.similar_group_id = group.id
            img.similar_group_id = group.id
            existing.append(img)
            existing_by_group[group.id].append(img)
            logger.info("created group %d (distance=%d)", group.id, best_dist)
