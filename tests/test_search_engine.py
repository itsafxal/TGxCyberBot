import unittest
from search_engine import (
    QueryNormalizer, SearchIntent, FuzzyScorer, SearchEngine, MIN_SUGGESTION_SCORE
)

class TestSearchEngine(unittest.TestCase):

    def test_query_normalization(self):
        self.assertEqual(QueryNormalizer.normalize_text("Musafir.Cafe.S01"), "musafir cafe s01")
        self.assertEqual(QueryNormalizer.normalize_text("musafir_cafe_s1"), "musafir cafe s1")
        self.assertEqual(QueryNormalizer.normalize_text("MUSAFIR-CAFE"), "musafir cafe")
        self.assertEqual(QueryNormalizer.normalize_text("GD.Naidu.Movie.2023.1080p"), "gd naidu movie 2023 1080p")

    def test_intent_parsing(self):
        intent = SearchIntent("Musafir Cafe Season 1 Tamil 1080p")
        self.assertEqual(intent.clean_title, "musafir cafe")
        self.assertEqual(intent.season, 1)
        self.assertEqual(intent.language, "tamil")
        self.assertEqual(intent.quality, "1080p")
        self.assertIn("musafir", intent.meaningful_tokens)
        self.assertIn("cafe", intent.meaningful_tokens)
        self.assertNotIn("season", intent.meaningful_tokens)

    def test_rejection_rule_common_word_only(self):
        """
        Query: "Musafir Cafe Season 1"
        Candidates containing only 'Season':
        - "Open Season Scared Silly"
        - "Hard Knocks In Season"
        - "Redemption A Season of Change"

        MUST return score 0.0 or below MIN_SUGGESTION_SCORE (70).
        """
        intent = SearchIntent("Musafir Cafe Season 1")

        bad_candidates = [
            "Open Season Scared Silly",
            "Hard Knocks In Season",
            "Redemption A Season of Change",
            "CC Season of Good Rain",
            "Cafe From 10bit 2CH PSA"
        ]

        for cand in bad_candidates:
            score, debug = FuzzyScorer.calculate_score(intent, cand)
            self.assertLess(
                score, MIN_SUGGESTION_SCORE,
                f"Candidate '{cand}' scored {score}, expected < {MIN_SUGGESTION_SCORE}. Debug: {debug}"
            )

    def test_strong_matches(self):
        intent = SearchIntent("Musafir Cafe Season 1")

        good_candidates = [
            "Musafir Cafe",
            "Musafir Cafe S01",
            "Musafir Cafe Season 1",
            "Musafir.Cafe.S01.1080p.WEB-DL"
        ]

        for cand in good_candidates:
            score, debug = FuzzyScorer.calculate_score(intent, cand)
            self.assertGreaterEqual(
                score, MIN_SUGGESTION_SCORE,
                f"Candidate '{cand}' scored {score}, expected >= {MIN_SUGGESTION_SCORE}. Debug: {debug}"
            )

    def test_typo_tolerance(self):
        intent_typo = SearchIntent("interstelar")
        score, _ = FuzzyScorer.calculate_score(intent_typo, "Interstellar (2014) 1080p")
        self.assertGreaterEqual(score, MIN_SUGGESTION_SCORE)

        intent_typo2 = SearchIntent("musafir cefe")
        score2, _ = FuzzyScorer.calculate_score(intent_typo2, "Musafir Cafe S01")
        self.assertGreaterEqual(score2, MIN_SUGGESTION_SCORE)

    def test_transliteration_support(self):
        intent_mal = SearchIntent("പ്രേമം malayalam")
        score, _ = FuzzyScorer.calculate_score(intent_mal, "Premam (2015) Malayalam 720p")
        self.assertGreaterEqual(score, MIN_SUGGESTION_SCORE)

        intent_tam = SearchIntent("கைதி tamil")
        score2, _ = FuzzyScorer.calculate_score(intent_tam, "Kaithi 2019 Tamil HDRip")
        self.assertGreaterEqual(score2, MIN_SUGGESTION_SCORE)

    def test_year_matching(self):
        intent_year = SearchIntent("Leo 2023")
        score_2023, _ = FuzzyScorer.calculate_score(intent_year, "Leo (2023) 1080p")
        score_2010, _ = FuzzyScorer.calculate_score(intent_year, "Leo (2010) 720p")

        self.assertGreater(score_2023, score_2010)

    def test_additional_query_test_cases(self):
        # 1. "GD naidu movie tamil"
        intent_gd = SearchIntent("GD naidu movie tamil")
        score_gd, _ = FuzzyScorer.calculate_score(intent_gd, "GD Naidu (2023) Tamil HDRip 1080p")
        self.assertGreaterEqual(score_gd, MIN_SUGGESTION_SCORE)

        # 2. "vikram 2022"
        intent_vikram = SearchIntent("vikram 2022")
        score_vikram, _ = FuzzyScorer.calculate_score(intent_vikram, "Vikram 2022 Tamil 1080p WEB-DL")
        self.assertGreaterEqual(score_vikram, MIN_SUGGESTION_SCORE)

        # 3. "leo tamil"
        intent_leo = SearchIntent("leo tamil")
        score_leo, _ = FuzzyScorer.calculate_score(intent_leo, "Leo (2023) Tamil WEB-DL 720p")
        self.assertGreaterEqual(score_leo, MIN_SUGGESTION_SCORE)

        # 4. "kaithi tamil"
        intent_kaithi = SearchIntent("kaithi tamil")
        score_kaithi, _ = FuzzyScorer.calculate_score(intent_kaithi, "Kaithi 2019 Tamil HDRip 1080p")
        self.assertGreaterEqual(score_kaithi, MIN_SUGGESTION_SCORE)

    def test_deduplication(self):
        candidates = [
            (95.0, "Musafir Cafe S01 480p", {}),
            (98.0, "Musafir Cafe S01 720p", {}),
            (99.0, "Musafir Cafe S01 1080p", {}),
            (90.0, "Musafir Cafe S01 WEB-DL", {})
        ]
        suggestions = SearchEngine.group_and_deduplicate(candidates, max_results=5)
        self.assertEqual(len(suggestions), 1)
        self.assertIn("Musafir Cafe", suggestions[0])

if __name__ == '__main__':
    unittest.main()
