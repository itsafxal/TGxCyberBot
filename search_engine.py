import re
import unicodedata
import difflib
from typing import List, Dict, Any, Tuple, Optional, Set

# --- Configuration & Constants ---

MIN_SUGGESTION_SCORE = 70.0

GENERIC_STOPWORDS = {
    "movie", "movies", "film", "films", "series", "season", "seasons",
    "ep", "episode", "episodes", "the", "a", "an", "of", "in", "on",
    "at", "and", "or", "to", "for", "with", "by", "from", "part", "vol",
    "volume", "hd", "full", "download", "tamil", "hindi", "malayalam",
    "telugu", "kannada", "english", "multi", "dual", "1080p", "720p",
    "480p", "360p", "2160p", "4k", "bluray", "webrip", "web-dl", "web",
    "hevc", "x264", "x265", "esubs", "esub", "msub", "aac", "ddp5.1", "dd5.1"
}

TRANSLITERATION_MAP = {
    # Malayalam
    "പ്രേമം": "premam",
    "ജി ഡി നായിഡു": "gd naidu",
    "വിക്രം": "vikram",
    "അമരൻ": "amaran",
    "ലൂസിഫർ": "lucifer",
    "ദൃശ്യം": "drishyam",
    # Tamil
    "கைதி": "kaithi",
    "விக்ரம்": "vikram",
    "ஜி டி நாயுடு": "gd naidu",
    "லியோ": "leo",
    "அமரன்": "amaran",
    "ஜெயிலர்": "jailer",
    # Telugu
    "విక్రమ్": "vikram",
    "కాంతార": "kantara",
    "పుష్ప": "pushpa",
    # Kannada
    "ಕೆಜಿಎಫ್": "kgf",
    "ಕಾಂತಾರ": "kantara",
    # Hindi
    "मुसाफिर": "musafir",
    "कैफे": "cafe",
    "जवान": "jawan",
    "पठान": "pathaan"
}

LANGUAGES_SET = {"tamil", "hindi", "malayalam", "telugu", "kannada", "english", "multi", "dual"}
QUALITIES_SET = {"1080p", "720p", "480p", "360p", "2160p", "4k", "576p"}

# --- 1. Query Normalization & Release Cleaning ---

class QueryNormalizer:
    @staticmethod
    def normalize_text(text: str) -> str:
        """Lowers text, normalizes unicode, converts transliterated scripts, strips punctuation/emojis."""
        if not text:
            return ""

        # Normalize unicode (NFKD)
        text = unicodedata.normalize('NFKD', text)

        # Lowercase
        text = text.lower()

        # Check for transliteration replacements
        for script_term, latin_term in TRANSLITERATION_MAP.items():
            if script_term in text:
                text = text.replace(script_term, latin_term)

        # Remove telegram tags (@channel), URLs
        text = re.sub(r'@[a-zA-Z0-9_]+', ' ', text)
        text = re.sub(r'https?://\S+|www\.\S+', ' ', text)

        # Replace non-alphanumeric (except spaces) with space
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'[\._\-\[\(\]\):\=]+', ' ', text)

        # Collapse spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def clean_release_name(filename: str) -> str:
        """Cleans raw release filenames by stripping file extensions, channel tags, and release metadata."""
        if not filename:
            return ""

        # Strip file extensions
        title = re.sub(r'\.(mkv|mp4|avi|webm|flv|mov|m4v|3gp|zip|rar|tar|gz|7z)$', '', filename, flags=re.IGNORECASE)

        # Remove telegram tags & URLs
        title = re.sub(r'@[a-zA-Z0-9_]+', ' ', title)
        title = re.sub(r'https?://\S+|www\.\S+', ' ', title)

        # Remove release tags (codecs, resolutions, audio)
        pattern = (
            r'(?i)\b(1080p|720p|480p|360p|2160p|4k|576p|hdr|webrip|web-dl|web|bluray|hdrip|dvdrip|brrip|'
            r'x264|x265|hevc|h264|esub|esubs|msub|sub|subtitle|subtitles|hindi|malayalam|tamil|telugu|'
            r'kannada|english|multi|dual|audio|aac|ddp5\.1|dd5\.1|atmos|10bit|8bit|2ch|6ch|psa|dl|mkv|mp4)\b'
        )
        title = re.sub(pattern, ' ', title)

        # Replace dots, underscores, hyphens, brackets with spaces
        title = re.sub(r'[\._\-\[\]\(\)\:\=]+', ' ', title)

        # Strip season & episode patterns e.g. S01E01, S01, Season 1
        title = re.sub(r'(?i)\b(s\d{1,2}|season\s*\d{1,2})(?:[\s._-]*(e\d{1,2}|episode\s*\d{1,2}))?\b', ' ', title)
        title = re.sub(r'(?i)\[s\d{1,2}\s*(ep?\d{1,2})?\]', ' ', title)

        # Strip standalone years e.g. 1999, 2023 if surrounded by boundary
        title = re.sub(r'\b(19\d\d|20[0-3]\d)\b', ' ', title)

        # Collapse spaces
        title = re.sub(r'\s+', ' ', title).strip()
        return title


# --- 2. Intent Parsing ---

class SearchIntent:
    def __init__(self, raw_query: str):
        self.raw_query: str = raw_query
        self.clean_query: str = QueryNormalizer.normalize_text(raw_query)
        self.year: Optional[int] = None
        self.season: Optional[int] = None
        self.episode: Optional[int] = None
        self.language: Optional[str] = None
        self.quality: Optional[str] = None
        self.clean_title: str = ""
        self.title_tokens: List[str] = []
        self.meaningful_tokens: List[str] = []

        self._parse()

    def _parse(self):
        text = self.clean_query

        # Extract Year (1920-2035)
        year_match = re.search(r'\b(19[2-9]\d|20[0-3]\d)\b', text)
        if year_match:
            self.year = int(year_match.group(1))
            text = re.sub(r'\b' + year_match.group(1) + r'\b', ' ', text)

        # Extract Season & Episode
        # Patterns: s01e01, s1e1, season 1 episode 1, s01, season 1
        se_match = re.search(r'\b(?:s|season)\s*(\d{1,2})(?:\s*(?:e|ep|episode)\s*(\d{1,2}))?\b', text, re.IGNORECASE)
        if se_match:
            self.season = int(se_match.group(1))
            if se_match.group(2):
                self.episode = int(se_match.group(2))
            text = re.sub(re.escape(se_match.group(0)), ' ', text, flags=re.IGNORECASE)
        else:
            # Standalone episode check e.g. ep01, e01
            ep_match = re.search(r'\b(?:e|ep|episode)\s*(\d{1,2})\b', text, re.IGNORECASE)
            if ep_match:
                self.episode = int(ep_match.group(1))
                text = re.sub(re.escape(ep_match.group(0)), ' ', text, flags=re.IGNORECASE)

        # Extract Language
        for lang in LANGUAGES_SET:
            if re.search(r'\b' + lang + r'\b', text, re.IGNORECASE):
                self.language = lang
                text = re.sub(r'\b' + lang + r'\b', ' ', text, flags=re.IGNORECASE)
                break

        # Extract Quality
        for qual in QUALITIES_SET:
            if re.search(r'\b' + qual + r'\b', text, re.IGNORECASE):
                self.quality = qual
                text = re.sub(r'\b' + qual + r'\b', ' ', text, flags=re.IGNORECASE)
                break

        # Clean title
        title = re.sub(r'\s+', ' ', text).strip()
        # Remove leftover release keywords
        for word in ["movie", "movies", "film", "series", "hd"]:
            title = re.sub(r'\b' + word + r'\b', ' ', title, flags=re.IGNORECASE)

        title = re.sub(r'\s+', ' ', title).strip()
        self.clean_title = title if title else self.clean_query

        # Tokenize
        tokens = [t for t in self.clean_title.split() if t]
        self.title_tokens = tokens
        self.meaningful_tokens = [t for t in tokens if t.lower() not in GENERIC_STOPWORDS and len(t) >= 2]
        if not self.meaningful_tokens:
            # Fallback to all non-stopword tokens or raw tokens if all were filtered
            self.meaningful_tokens = [t for t in tokens if len(t) >= 2] or tokens


# --- 3. Tokenizer & Stopword IDF ---

class StopwordIDF:
    @staticmethod
    def is_generic(token: str) -> bool:
        return token.lower() in GENERIC_STOPWORDS

    @staticmethod
    def get_token_weight(token: str) -> float:
        t_low = token.lower()
        if t_low in GENERIC_STOPWORDS:
            return 0.1
        if len(token) <= 2:
            return 0.5
        if len(token) <= 4:
            return 0.8
        return 1.2


# --- 4. Fuzzy Scorer ---

class FuzzyScorer:
    @staticmethod
    def lev_ratio(s1: str, s2: str) -> float:
        """Computes SequenceMatcher ratio between two strings."""
        if not s1 or not s2:
            return 0.0
        return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

    @staticmethod
    def is_token_match(t1: str, t2: str) -> bool:
        """Determines if two tokens match considering exact match, prefix, and length-aware typo tolerance."""
        t1, t2 = t1.lower(), t2.lower()
        if t1 == t2:
            return True
        # For short tokens (<= 3 chars), require exact match
        if len(t1) <= 3 or len(t2) <= 3:
            return False
        # Prefix match for words >= 5 chars
        if len(t1) >= 5 and len(t2) >= 5:
            if t1.startswith(t2) or t2.startswith(t1):
                return True
        # Typo tolerance ratio >= 0.82 for words >= 4 chars
        ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
        return ratio >= 0.82

    @classmethod
    def calculate_score(cls, intent: SearchIntent, candidate_raw: str) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates a transparent score (0-100) comparing a SearchIntent against a candidate filename.
        Returns (final_score, debug_dict).
        """
        cand_clean = QueryNormalizer.normalize_text(candidate_raw)
        cand_title = QueryNormalizer.clean_release_name(candidate_raw)
        cand_title_norm = QueryNormalizer.normalize_text(cand_title)

        cand_tokens = [t for t in cand_title_norm.split() if t]

        # Extract candidate season/episode/year/language
        cand_intent = SearchIntent(candidate_raw)

        # ----------------------------------------------------
        # CRITICAL REJECTION CHECK (Multi-word & Meaningful match)
        # ----------------------------------------------------
        query_meaningful = intent.meaningful_tokens
        matched_meaningful = []
        for qt in query_meaningful:
            for ct in cand_tokens:
                if cls.is_token_match(qt, ct):
                    matched_meaningful.append(qt)
                    break

        # If query has meaningful tokens, but candidate matches NONE of them, score = 0
        if query_meaningful and not matched_meaningful:
            return 0.0, {"reason": "zero_meaningful_tokens_matched"}

        # If query has multiple meaningful tokens (e.g. "musafir", "cafe"), require at least 50% of them to match
        if len(query_meaningful) >= 2 and len(matched_meaningful) < (len(query_meaningful) // 2 + 1):
            # Exception: if overall string similarity is extremely high
            str_sim = cls.lev_ratio(intent.clean_title, cand_title_norm)
            if str_sim < 0.75:
                return 0.0, {"reason": "insufficient_meaningful_token_overlap"}

        # ----------------------------------------------------
        # SCORING COMPONENTS
        # ----------------------------------------------------

        # 1. Exact normalized title match
        exact_match = 0.0
        if intent.clean_title and (intent.clean_title == cand_title_norm or intent.clean_title == cand_clean):
            exact_match = 100.0
        elif intent.clean_title and (cand_title_norm.startswith(intent.clean_title) or intent.clean_title.startswith(cand_title_norm)):
            exact_match = 92.0

        # 2. Token overlap & IDF score
        matched_weight = sum(StopwordIDF.get_token_weight(t) for t in matched_meaningful)
        total_weight = sum(StopwordIDF.get_token_weight(t) for t in query_meaningful) or 1.0
        token_ratio = min(1.0, matched_weight / total_weight)
        token_score = token_ratio * 90.0

        # 3. Fuzzy String Ratio
        fuzzy_ratio = cls.lev_ratio(intent.clean_title, cand_title_norm)
        fuzzy_score = fuzzy_ratio * 90.0

        # Base Title Score
        if exact_match > 0:
            base_score = exact_match
        else:
            base_score = max(token_score, fuzzy_score)

        # 4. Metadata Adjustments
        meta_score = 0.0

        # Season match
        if intent.season is not None:
            if cand_intent.season == intent.season:
                meta_score += 10.0
            elif cand_intent.season is not None and cand_intent.season != intent.season:
                meta_score -= 20.0  # Mismatched season penalty

        # Episode match
        if intent.episode is not None:
            if cand_intent.episode == intent.episode:
                meta_score += 5.0

        # Year match
        if intent.year is not None:
            if cand_intent.year == intent.year:
                meta_score += 5.0
            elif cand_intent.year is not None and cand_intent.year != intent.year:
                meta_score -= 15.0  # Mismatched year penalty

        # Language match
        if intent.language is not None:
            if cand_intent.language == intent.language or intent.language in cand_clean:
                meta_score += 5.0

        # 5. Final Composite Score
        final_score = base_score + meta_score

        # Cap at 100.0 max, 0.0 min
        final_score = max(0.0, min(100.0, final_score))

        debug_info = {
            "query": intent.raw_query,
            "clean_title": intent.clean_title,
            "cand_title": cand_title_norm,
            "matched_meaningful": matched_meaningful,
            "base_score": base_score,
            "meta_score": meta_score,
            "final_score": final_score
        }

        return final_score, debug_info


# --- 5. Database Candidate Retrieval & Search Engine ---

class SearchEngine:
    @staticmethod
    def group_and_deduplicate(scored_candidates: List[Tuple[float, str, Any]], max_results: int = 5) -> List[str]:
        """Groups duplicate release files by clean title, keeping the highest scoring entry."""
        seen_titles: Set[str] = set()
        suggestions: List[str] = []

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        for score, file_name, _ in scored_candidates:
            clean_display = QueryNormalizer.clean_release_name(file_name)
            if not clean_display or len(clean_display) < 2:
                clean_display = file_name.strip()

            # Deduplicate by lower clean title
            dedup_key = clean_display.lower()
            if dedup_key in seen_titles:
                continue

            seen_titles.add(dedup_key)
            suggestions.append(clean_display)

            if len(suggestions) >= max_results:
                break

        return suggestions

    @classmethod
    async def get_suggestions_sql(
        cls,
        db_conn,
        search_query: str,
        limit: int = 5,
        min_score: float = MIN_SUGGESTION_SCORE
    ) -> List[str]:
        """
        High-precision suggestion generator for SQLite database.
        1. Parses query intent.
        2. Retrieves top 50-100 candidates from DB using SQL LIKE queries on meaningful tokens.
        3. Computes FuzzyScorer on candidates.
        4. Filters candidates >= min_score (70).
        5. Deduplicates and returns top suggestions.
        """
        if not search_query or len(search_query.strip()) < 2:
            return []

        intent = SearchIntent(search_query)
        meaningful = intent.meaningful_tokens

        if not meaningful:
            meaningful = intent.title_tokens

        if not meaningful:
            return []

        # Retrieve candidates from SQLite
        where_clauses = []
        params = []
        for word in meaningful[:4]:  # limit to top 4 tokens
            where_clauses.append("file_name LIKE ?")
            params.append(f"%{word}%")
            if len(word) >= 4:
                prefix = word[:3]
                where_clauses.append("file_name LIKE ?")
                params.append(f"%{prefix}%")

        where_stmt = " OR ".join(where_clauses)
        query = f"SELECT DISTINCT file_name FROM media WHERE {where_stmt} LIMIT 150"

        candidate_rows = []
        try:
            async with db_conn.execute(query, tuple(params)) as cursor:
                candidate_rows = await cursor.fetchall()
        except Exception:
            # Fallback if error
            try:
                async with db_conn.execute("SELECT DISTINCT file_name FROM media ORDER BY date_saved DESC LIMIT 100") as cursor:
                    candidate_rows = await cursor.fetchall()
            except Exception:
                candidate_rows = []

        if not candidate_rows:
            return []

        scored_list: List[Tuple[float, str, Any]] = []
        for row in candidate_rows:
            fn = row[0]
            if not fn:
                continue
            score, debug = FuzzyScorer.calculate_score(intent, fn)
            if score >= min_score:
                scored_list.append((score, fn, debug))

        # Deduplicate & return top suggestions
        return cls.group_and_deduplicate(scored_list, max_results=limit)
