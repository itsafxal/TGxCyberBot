import unittest
import asyncio
import os
import sys

# Ensure root folder is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.announcement import (
    extract_and_filter_languages,
    extract_qualities,
    sort_qualities,
    format_post_caption,
    clean_movie_title_and_year,
    init_announcements_db
)

class TestAnnouncementRefactor(unittest.TestCase):
    def test_language_filtering(self):
        # Indian languages allowed
        langs, allowed = extract_and_filter_languages("KGF.Chapter.1.2018.720p.Malayalam.Tamil.Hindi.mkv")
        self.assertTrue(allowed)
        self.assertIn("Malayalam", langs)
        self.assertIn("Tamil", langs)
        self.assertIn("Hindi", langs)

        # Japanese allowed
        langs, allowed = extract_and_filter_languages("Demon.Slayer.S01.720p.Japanese.EngSub.mkv")
        self.assertTrue(allowed)
        self.assertIn("Japanese", langs)

        # English allowed
        langs, allowed = extract_and_filter_languages("Inception.2010.1080p.English.mkv")
        self.assertTrue(allowed)
        self.assertIn("English", langs)

        # Disallowed language (e.g. Spanish only) -> Should be filtered out
        langs, allowed = extract_and_filter_languages("Casa.De.Papel.S01.1080p.Spanish.mkv")
        self.assertFalse(allowed)

        # Disallowed language (e.g. Korean only) -> Should be filtered out
        langs, allowed = extract_and_filter_languages("Squid.Game.S01.1080p.Korean.mkv")
        self.assertFalse(allowed)

    def test_quality_extraction_and_sorting(self):
        qualities = extract_qualities("KGF.Chapter.1.2018.1080p.720p.4K.WEB-DL.mkv")
        self.assertEqual(qualities, ["720p", "1080p", "4K", "WEB-DL"])

    def test_caption_formatting(self):
        caption = format_post_caption(
            title="KGF Chapter 1",
            year="2018",
            languages=["Malayalam", "Tamil", "Telugu", "Hindi", "Kannada"],
            rating="8.2/10",
            qualities=["720p", "1080p"]
        )
        self.assertIn("🎬 <b>Title:</b> KGF Chapter 1 (2018)", caption)
        self.assertIn("🎙 <b>Languages:</b> Malayalam, Tamil, Telugu, Hindi, Kannada", caption)
        self.assertIn("⭐ <b>Rating:</b> ⭐ 8.2/10", caption)
        self.assertIn("📽 <b>Quality/Formats:</b> 720p, 1080p", caption)

class TestAsyncAnnouncementDB(unittest.IsolatedAsyncioTestCase):
    async def test_init_announcements_db(self):
        from sql.db import ensure_aiosqlite_connection
        db = await ensure_aiosqlite_connection()
        await init_announcements_db()
        
        async with db.execute("PRAGMA table_info(announcements)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        
        self.assertIn("movie_key", columns)
        self.assertIn("title", columns)
        self.assertIn("year", columns)
        self.assertIn("languages", columns)
        self.assertIn("qualities", columns)
        self.assertIn("channel_messages", columns)

if __name__ == "__main__":
    unittest.main()
