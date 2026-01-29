import difflib
import logging
import re
from typing import Any, Optional, Dict, List
from .display import print_match_details

logger = logging.getLogger(__name__)


def verify_filetype(file: Dict[str, Any], allowed_filetype: str) -> bool:
    current_filetype = file["filename"].split(".")[-1].lower()
    logger.debug(f"Current file type: {current_filetype}")
    if current_filetype == allowed_filetype.split(" ")[0]:
        return True
    else:
        return False


def check_ratio(separator: str, ratio: float, book_filename: str, slskd_filename: str, minimum_match_ratio: float) -> float:
    if ratio < minimum_match_ratio:
        if separator != "":
            book_filename_word_count = len(book_filename.split()) * -1
            truncated_slskd_filename = " ".join(slskd_filename.split(separator)[book_filename_word_count:])
            ratio = difflib.SequenceMatcher(None, book_filename, truncated_slskd_filename).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, book_filename, slskd_filename).ratio()
        return ratio
    return ratio


def book_match(
    target: Dict[str, Any],
    slskd_files: List[Dict[str, Any]],
    username: str,
    filetype: str,
    ignored_users: List[str],
    minimum_match_ratio: float,
) -> Optional[Dict[str, Any]]:
    """
    Match target book with available files, filtering by correct filetype.
    Enhanced to handle variations in punctuation, underscores, and additional text.

    Args:
        target: Target book information
        slskd_files: List of available files
        username: Username of the file owner
        filetype: Required file type (e.g., 'epub', 'pdf')
        ignored_users: List of ignored users
        minimum_match_ratio: Minimum ratio to consider a match

    Returns:
        Matching file object or None
    """
    book_title = target["book"]["title"]
    author_name = target["author"]["authorName"]
    best_match = 0.0
    current_match = None

    # Filter files by the correct filetype first
    filtered_files = []
    for slskd_file in slskd_files:
        if verify_filetype(slskd_file, filetype):
            filtered_files.append(slskd_file)

    # If no files match the desired filetype, return None
    if not filtered_files:
        logger.debug(f"No files found matching filetype: {filetype}")
        return None

    # Helper function to normalize strings for better matching
    def normalize_for_matching(text):
        """Normalize text for better matching by handling common variations"""
        # Convert to lowercase
        text = text.lower()
        # Replace underscores with spaces
        text = text.replace("_", " ")
        # Remove common punctuation that might vary
        text = re.sub(r"[^\w\s]", " ", text)
        # Normalize multiple spaces to single space
        text = re.sub(r"\s+", " ", text)
        # Strip whitespace
        return text.strip()

    # Helper function to check if target title is contained in filename
    def title_contained_in_filename(target_title, filename):
        """Check if the target title is contained in the filename with fuzzy matching"""
        normalized_target = normalize_for_matching(target_title)
        normalized_filename = normalize_for_matching(filename)

        # Check direct containment
        if normalized_target in normalized_filename:
            return True

        # Check word-by-word containment for partial matches
        target_words = set(normalized_target.split())
        filename_words = set(normalized_filename.split())

        # If most of the target words are in the filename, it's likely a match
        overlap = len(target_words.intersection(filename_words))
        return overlap >= len(target_words) * 0.7  # 70% word overlap

    for slskd_file in filtered_files:
        slskd_filename = slskd_file["filename"]
        logger.info(f"Checking ratio on {slskd_filename} vs wanted {book_title} - {author_name}.{filetype.split(' ')[0]}")

        # First, check if this looks like a very good match based on title containment
        title_bonus = 0.0
        if title_contained_in_filename(book_title, slskd_filename):
            title_bonus = 0.3  # Significant bonus for files that clearly contain the target title
            logger.info(f"Title containment bonus applied: +{title_bonus}")

        # Try multiple filename patterns for matching
        patterns_to_try = [
            f"{book_title} - {author_name}.{filetype.split(' ')[0]}",
            f"{author_name} - {book_title}.{filetype.split(' ')[0]}",
            f"{book_title}.{filetype.split(' ')[0]}",
            f"{author_name} {book_title}.{filetype.split(' ')[0]}",
        ]

        max_ratio = 0.0

        for pattern in patterns_to_try:
            # Direct ratio
            ratio = difflib.SequenceMatcher(None, pattern, slskd_filename).ratio()
            max_ratio = max(max_ratio, ratio)

            # Try with normalized strings for better matching
            normalized_pattern = normalize_for_matching(pattern)
            normalized_filename = normalize_for_matching(slskd_filename)
            normalized_ratio = difflib.SequenceMatcher(None, normalized_pattern, normalized_filename).ratio()
            max_ratio = max(max_ratio, normalized_ratio)

            # Try with different separators
            ratio = check_ratio(" ", ratio, pattern, slskd_filename, minimum_match_ratio)
            max_ratio = max(max_ratio, ratio)

            ratio = check_ratio("_", ratio, pattern, slskd_filename, minimum_match_ratio)
            max_ratio = max(max_ratio, ratio)

        # Apply title bonus if applicable
        final_ratio = max_ratio + title_bonus

        if final_ratio > best_match:
            logger.info(f"New best match found! Ratio: {max_ratio:.3f} + Title bonus: {title_bonus:.3f} = {final_ratio:.3f}")
            best_match = final_ratio
            current_match = slskd_file
        else:
            logger.info(f"Ratio: {max_ratio:.3f} + Title bonus: {title_bonus:.3f} = {final_ratio:.3f} (not better than current best: {best_match:.3f})")

    if (current_match != None) and (username not in ignored_users) and (best_match >= minimum_match_ratio):
        # Only show the SUCCESSFUL MATCH message and the pretty table
        logger.info("SUCCESSFUL MATCH")

        # Print beautiful match details (this contains all the info we need)
        print_match_details(current_match["filename"], best_match, username, filetype)

        logger.info("-------------------")
        return current_match

    return None
