#!/usr/bin/env python3
"""
Standalone Cross-Database Deduplication & Cleanup Script.
Scans DB2 and DB3, eliminates duplicate mirrored files residing in DB3,
and frees storage so each file exists in ONLY ONE database.
"""

import asyncio
import logging
import sys
import time
from datetime import timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DeleteOne
from pymongo.errors import BulkWriteError

from info import DATABASE_URI2, DATABASE_URI3, DATABASE_NAME, COLLECTION_NAME

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cleanup_duplicates")

BATCH_SIZE = 5000  # Process 5,000 documents per batch

async def cleanup_duplicates():
    start_time = time.time()
    logger.info("🚀 Starting Cross-Database Deduplication & Storage Cleanup...")

    client2 = AsyncIOMotorClient(DATABASE_URI2)
    db2 = client2[DATABASE_NAME]
    col2 = db2[COLLECTION_NAME]

    client3 = AsyncIOMotorClient(DATABASE_URI3)
    db3 = client3[DATABASE_NAME]
    col3 = db3[COLLECTION_NAME]

    # Count total documents
    count2_task = col2.count_documents({})
    count3_task = col3.count_documents({})
    total_db2, total_db3 = await asyncio.gather(count2_task, count3_task)

    logger.info(f"📊 Initial Status -> DB2 Count: {total_db2:,} | DB3 Count: {total_db3:,}")

    if total_db2 == 0 or total_db3 == 0:
        logger.info("One of the databases is empty. No cross-duplicates to clean up.")
        return

    processed = 0
    total_duplicates_removed = 0
    cursor = col2.find({}, {"_id": 1}).batch_size(BATCH_SIZE)

    batch_ids = []

    async for doc in cursor:
        batch_ids.append(doc["_id"])
        processed += 1

        if len(batch_ids) >= BATCH_SIZE or processed == total_db2:
            # Check which of these IDs exist in DB3
            db3_existing = await col3.find({"_id": {"$in": batch_ids}}, {"_id": 1}).to_list(length=None)
            dup_ids = [d["_id"] for d in db3_existing]

            if dup_ids:
                delete_requests = [DeleteOne({"_id": fid}) for fid in dup_ids]
                try:
                    res = await col3.bulk_write(delete_requests, ordered=False)
                    removed = res.deleted_count
                except BulkWriteError as bwe:
                    removed = bwe.details.get("nRemoved", 0)
                except Exception as e:
                    logger.error(f"Error executing bulk delete on DB3: {e}")
                    removed = 0

                total_duplicates_removed += removed

            batch_ids.clear()

            # Calculate progress & ETA
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            remaining_docs = total_db2 - processed
            eta_seconds = remaining_docs / rate if rate > 0 else 0

            percent = (processed / total_db2) * 100
            bar_len = 30
            filled_len = int(bar_len * percent // 100)
            bar = '█' * filled_len + '-' * (bar_len - filled_len)

            eta_str = str(timedelta(seconds=int(eta_seconds)))
            elapsed_str = str(timedelta(seconds=int(elapsed)))

            logger.info(
                f"[{bar}] {percent:5.1f}% | Processed: {processed:,}/{total_db2:,} | "
                f"Removed: {total_duplicates_removed:,} | Speed: {rate:6.1f} doc/s | "
                f"Elapsed: {elapsed_str} | ETA: {eta_str}"
            )

    total_time = time.time() - start_time
    total_time_str = str(timedelta(seconds=int(total_time)))

    # Get final counts
    final_count2 = await col2.count_documents({})
    final_count3 = await col3.count_documents({})

    logger.info("=" * 60)
    logger.info("✅ CROSS-DATABASE DEDUPLICATION COMPLETE!")
    logger.info(f"⏱ Total Duration: {total_time_str}")
    logger.info(f"🗑 Total Duplicate Files Removed from DB3: {total_duplicates_removed:,}")
    logger.info(f"📉 DB2 Final Count: {final_count2:,}")
    logger.info(f"📉 DB3 Final Count: {final_count3:,}")
    logger.info(f"💾 Storage Freed: Each file now exists in ONLY ONE database.")
    logger.info("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(cleanup_duplicates())
    except KeyboardInterrupt:
        logger.info("\n🛑 Cleanup script interrupted by user.")
    except Exception as e:
        logger.critical(f"Fatal error in cleanup script: {e}", exc_info=True)
