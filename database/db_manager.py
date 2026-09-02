import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import InsertOne, UpdateOne, DeleteOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

from info import DATABASE_URI2, DATABASE_URI3, DATABASE_NAME, COLLECTION_NAME

logger = logging.getLogger(__name__)

# --- High-Performance In-Memory LRU Cache ---
class FastLRUCache:
    """Thread-safe / Async-safe LRU Cache for deduplication lookup."""
    def __init__(self, max_size: int = 100000):
        self.cache: OrderedDict[str, bool] = OrderedDict()
        self.max_size = max_size
        self._lock = asyncio.Lock()

    async def contains(self, key: str) -> bool:
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return True
            return False

    async def add(self, key: str):
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                self.cache[key] = True
                if len(self.cache) > self.max_size:
                    self.cache.popitem(last=False)

    async def add_batch(self, keys: List[str]):
        async with self._lock:
            for key in keys:
                self.cache[key] = True
                if len(self.cache) > self.max_size:
                    self.cache.popitem(last=False)

# --- Unified Multi-Database Manager ---
class UnifiedDatabaseManager:
    """
    Production-grade Unified Database Manager for Motor (MongoDB).
    Provides cross-database deduplication, 50/50 deterministic sharding,
    and parallel asynchronous querying across DB2 and DB3.
    """
    def __init__(
        self,
        uri2: str = DATABASE_URI2,
        uri3: str = DATABASE_URI3,
        db_name: str = DATABASE_NAME,
        collection_name: str = COLLECTION_NAME,
        cache_size: int = 100000
    ):
        self.client2 = AsyncIOMotorClient(uri2)
        self.db2 = self.client2[db_name]
        self.col2 = self.db2[collection_name]

        self.client3 = AsyncIOMotorClient(uri3)
        self.db3 = self.client3[db_name]
        self.col3 = self.db3[collection_name]

        self.dedup_cache = FastLRUCache(max_size=cache_size)
        logger.info("UnifiedDatabaseManager initialized for DB2 and DB3.")

    async def create_indexes(self):
        """Ensures compound text & single-field indexes exist on both shards."""
        index_tasks = [
            self.col2.create_index([("file_name", "text"), ("caption", "text")]),
            self.col2.create_index([("file_name", 1)]),
            self.col2.create_index([("date", -1)]),
            self.col3.create_index([("file_name", "text"), ("caption", "text")]),
            self.col3.create_index([("file_name", 1)]),
            self.col3.create_index([("date", -1)]),
        ]
        await asyncio.gather(*index_tasks, return_exceptions=True)
        logger.info("Database indexes initialized on DB2 and DB3.")

    def get_shard_index(self, file_unique_id: str) -> int:
        """
        Deterministic 50/50 sharding using MD5 hash.
        Returns 0 for DB2, 1 for DB3.
        """
        digest = hashlib.md5(file_unique_id.encode('utf-8')).hexdigest()
        return int(digest, 16) % 2

    async def file_exists_cross_db(self, file_id: str) -> bool:
        """Checks whether file exists in LRU cache or across DB2 and DB3."""
        if await self.dedup_cache.contains(file_id):
            return True

        res2_task = self.col2.find_one({"_id": file_id}, {"_id": 1})
        res3_task = self.col3.find_one({"_id": file_id}, {"_id": 1})

        doc2, doc3 = await asyncio.gather(res2_task, res3_task, return_exceptions=True)

        if doc2 or doc3:
            await self.dedup_cache.add(file_id)
            return True
        return False

    async def save_file(self, file_data: dict) -> bool:
        """
        Saves a single file document with cross-database deduplication
        and deterministic sharding. Returns True if inserted, False if duplicate.
        """
        file_id = file_data.get("_id") or file_data.get("file_id")
        if not file_id:
            logger.error("Cannot save file: missing '_id' or 'file_id'")
            return False

        file_data["_id"] = file_id

        # 1. Deduplication Check
        if await self.file_exists_cross_db(file_id):
            return False

        # 2. Deterministic Sharding
        shard_idx = self.get_shard_index(file_id)
        target_col = self.col2 if shard_idx == 0 else self.col3

        try:
            await target_col.insert_one(file_data)
            await self.dedup_cache.add(file_id)
            return True
        except DuplicateKeyError:
            await self.dedup_cache.add(file_id)
            return False
        except Exception as e:
            logger.error(f"Error inserting file {file_id}: {e}", exc_info=True)
            return False

    async def save_files_batch(self, file_list: List[dict]) -> Tuple[int, int, int]:
        """
        Mass batch insertion with parallel cross-database lookup
        and split-sharding. Returns (inserted_count, skipped_count, error_count).
        """
        if not file_list:
            return 0, 0, 0

        # Prepare normalized list & IDs
        valid_files = []
        file_ids = []
        for doc in file_list:
            fid = doc.get("_id") or doc.get("file_id")
            if fid:
                doc["_id"] = fid
                valid_files.append(doc)
                file_ids.append(fid)

        if not valid_files:
            return 0, 0, 0

        # 1. Filter out IDs already in in-memory LRU cache
        uncached_files = []
        uncached_ids = []
        cached_skips = 0

        for doc in valid_files:
            fid = doc["_id"]
            if await self.dedup_cache.contains(fid):
                cached_skips += 1
            else:
                uncached_files.append(doc)
                uncached_ids.append(fid)

        if not uncached_ids:
            return 0, cached_skips, 0

        # 2. Parallel cross-DB existence query
        q2_task = self.col2.find({"_id": {"$in": uncached_ids}}, {"_id": 1}).to_list(length=None)
        q3_task = self.col3.find({"_id": {"$in": uncached_ids}}, {"_id": 1}).to_list(length=None)

        res2, res3 = await asyncio.gather(q2_task, q3_task, return_exceptions=True)

        existing_ids = set()
        if isinstance(res2, list):
            existing_ids.update(doc["_id"] for doc in res2)
        if isinstance(res3, list):
            existing_ids.update(doc["_id"] for doc in res3)

        # Update cache with existing IDs found in DB
        await self.dedup_cache.add_batch(list(existing_ids))

        # 3. Partition new files into DB2 and DB3 shards
        batch2 = []
        batch3 = []
        skipped_count = cached_skips + len(existing_ids)

        for doc in uncached_files:
            fid = doc["_id"]
            if fid in existing_ids:
                continue

            if self.get_shard_index(fid) == 0:
                batch2.append(InsertOne(doc))
            else:
                batch3.append(InsertOne(doc))

        # 4. Perform parallel bulk insertions
        inserted_count = 0
        error_count = 0

        async def run_bulk(col, requests, new_ids):
            nonlocal inserted_count, error_count
            if not requests:
                return
            try:
                res = await col.bulk_write(requests, ordered=False)
                inserted_count += res.inserted_count
                await self.dedup_cache.add_batch(new_ids)
            except BulkWriteError as bwe:
                inserted_count += bwe.details.get("nInserted", 0)
                error_count += len(bwe.details.get("writeErrors", []))
            except Exception as e:
                logger.error(f"Bulk write error: {e}")
                error_count += len(requests)

        new_ids_2 = [req._doc["_id"] for req in batch2]
        new_ids_3 = [req._doc["_id"] for req in batch3]

        await asyncio.gather(
            run_bulk(self.col2, batch2, new_ids_2),
            run_bulk(self.col3, batch3, new_ids_3),
            return_exceptions=True
        )

        return inserted_count, skipped_count, error_count

    async def search_files(
        self, query_text: str, limit: int = 10, offset: int = 0
    ) -> Tuple[List[dict], int]:
        """
        Parallel search across DB2 and DB3 using asyncio.gather.
        Merges, ranks, deduplicates, and paginates results.
        """
        clean_query = query_text.strip()
        if not clean_query:
            return [], 0

        # Build regex words for flexible pattern search
        words = [w for w in re.split(r'\s+', clean_query) if len(w) > 1]
        if words:
            regex_pattern = r".*" + r".*".join(map(re.escape, words)) + r".*"
            filter_dict = {
                "$or": [
                    {"file_name": {"$regex": regex_pattern, "$options": "i"}},
                    {"caption": {"$regex": regex_pattern, "$options": "i"}}
                ]
            }
        else:
            filter_dict = {"$text": {"$search": clean_query}}

        # Query limit per shard: fetch enough to cover offset + limit
        fetch_limit = offset + limit + 50

        async def query_shard(col):
            try:
                cursor = col.find(filter_dict).sort("date", -1).limit(fetch_limit)
                return await cursor.to_list(length=fetch_limit)
            except Exception as e:
                logger.error(f"Error querying shard: {e}")
                return []

        # Execute search across DB2 and DB3 in parallel
        results2, results3 = await asyncio.gather(
            query_shard(self.col2),
            query_shard(self.col3),
            return_exceptions=True
        )

        list2 = results2 if isinstance(results2, list) else []
        list3 = results3 if isinstance(results3, list) else []

        # Combine & deduplicate by _id
        combined_dict = {}
        for doc in list2 + list3:
            fid = doc.get("_id")
            if fid and fid not in combined_dict:
                combined_dict[fid] = doc

        merged_results = list(combined_dict.values())

        # Sort merged results by date descending
        def get_date(d):
            dt = d.get("date")
            if isinstance(dt, datetime):
                return dt.timestamp()
            return 0.0

        merged_results.sort(key=get_date, reverse=True)

        total_found = len(merged_results)
        paginated_results = merged_results[offset : offset + limit]

        return paginated_results, total_found

# Singleton Global Manager Instance
db_manager = UnifiedDatabaseManager()
