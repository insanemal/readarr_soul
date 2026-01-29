import os
import re


def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', "", folder_name)
    return valid_characters.strip()


def is_docker():
    return os.getenv("IN_DOCKER") is not None


def get_current_page(path: str, default_page=1) -> int:
    if os.path.exists(path):
        with open(path, "r") as file:
            page_string = file.read().strip()
            if page_string:
                return int(page_string)
            else:
                with open(path, "w") as file:
                    file.write(str(default_page))
                return default_page
    else:
        with open(path, "w") as file:
            file.write(str(default_page))
        return default_page


def update_current_page(path: str, page: int) -> None:
    with open(path, "w") as file:
        file.write(str(page))


def normalize_for_matching(text: str) -> str:
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


def title_contained_in_filename(target_title: str, filename: str) -> bool:
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
    if not target_words:
        return False

    overlap = len(target_words.intersection(filename_words))
    return overlap >= len(target_words) * 0.7  # 70% word overlap
