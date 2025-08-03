#!/usr/bin/env python

import sys
sys.path.append(sys.path[0]+'./pyarr/')
import argparse
import math
import re
import os
import time
import shutil
import difflib
import operator
import traceback
import configparser
import logging
import copy
from mobi_header import MobiHeader
import ebookmeta
import pprint
from datetime import datetime
import music_tag
import slskd_api
from pyarr import ReadarrAPI
import filecmp
import requests

# Rich imports for beautiful logging
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.live import Live
from rich import box
from rich.align import Align

TERMINAL_WIDTH = 160
console = Console(
    width=TERMINAL_WIDTH,
    force_terminal=True,
    legacy_windows=False,
    no_color=False
)

def test_slskd_connection(slskd_client, max_retries=10, retry_delay=60):
    """
    Test SLSKD connection with retry logic and user-friendly error messages.

    Args:
        slskd_client: The SLSKD API client
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds

    Returns:
        bool: True if connection successful, False otherwise
    """
    # Use the global slskd_host_url variable instead of client attribute
    global slskd_host_url

    for attempt in range(max_retries + 1):
        try:
            # Test connection with a simple API call
            slskd_client.application.state()
            logger.info("✅ SLSKD connection successful")
            return True

        except requests.exceptions.ConnectionError as e:
            if attempt < max_retries:
                logger.warning(f"⚠️ SLSKD connection failed (attempt {attempt + 1}/{max_retries + 1})")
                logger.warning(f"🔌 Cannot reach SLSKD at: {slskd_host_url}")
                logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"❌ SLSKD connection failed after {max_retries + 1} attempts")
                logger.error(f"🔌 Cannot reach SLSKD at: {slskd_host_url}")
                logger.error("💡 Please check:")
                logger.error("   - SLSKD is running and accessible")
                logger.error("   - Host URL is correct in config.ini")
                logger.error("   - Network connectivity")
                logger.error("   - Firewall settings")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ SLSKD API error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error testing SLSKD connection: {e}")
            return False

    return False



def safe_slskd_call(func, *args, **kwargs):
    """
    Wrapper for SLSKD API calls with connection error handling.

    Args:
        func: The SLSKD API function to call
        *args, **kwargs: Arguments for the function

    Returns:
        Result of the function call, or None if connection failed
    """
    global slskd_host_url

    try:
        result = func(*args, **kwargs)
        return result
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 Lost connection to SLSKD during operation")
        logger.error(f"💔 Host: {slskd_host_url}")
        logger.error(f"🔍 Error: Connection refused")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ SLSKD API error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error in SLSKD call: {e}")
        return None


def check_slskd_recovery(max_attempts=3, delay=30):
    """
    Check if SLSKD connection can be recovered during operations.

    Args:
        max_attempts: Maximum recovery attempts
        delay: Delay between attempts in seconds

    Returns:
        bool: True if connection recovered, False otherwise
    """
    for attempt in range(max_attempts):
        try:
            slskd.application.state()
            logger.info(f"✅ SLSKD connection recovered on attempt {attempt + 1}")
            return True
        except Exception:
            if attempt < max_attempts - 1:
                logger.info(f"⏳ Connection recovery attempt {attempt + 1}/{max_attempts} failed, waiting {delay}s...")
                time.sleep(delay)

    logger.error(f"❌ Could not recover SLSKD connection after {max_attempts} attempts")
    return False


# Custom Rich Handler with better formatting
class CustomRichHandler(RichHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLevel(logging.INFO)

    def emit(self, record):
        # Add color coding based on log level
        if record.levelno >= logging.ERROR:
            record.msg = f"🚨 {record.msg}"
        elif record.levelno >= logging.WARNING:
            record.msg = f"⚠️  {record.msg}"
        elif record.levelno >= logging.INFO:
            if "SUCCESSFUL MATCH" in str(record.msg):
                record.msg = f"✅ {record.msg}"
            elif "Searching album" in str(record.msg):
                record.msg = f"🔍 {record.msg}"
            elif "Starting Readarr import" in str(record.msg):
                record.msg = f"📚 {record.msg}"
            elif "Downloads added" in str(record.msg):
                record.msg = f"⬇️  {record.msg}"
            elif "All tracks finished downloading" in str(record.msg):
                record.msg = f"🎉 {record.msg}"
            else:
                record.msg = f"ℹ️  {record.msg}"

        super().emit(record)

logger = logging.getLogger('readarr_soul')

# Enhanced logging configuration with Rich
DEFAULT_LOGGING_CONF = {
    'level': 'INFO',
    'format': '[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s',
    'datefmt': '%Y-%m-%dT%H:%M:%S%z',
}

def print_startup_banner():
    """Print a beautiful startup banner using full width"""
    banner_text = """
╔══════════════════════════════════════════════════════════════╗
║                         READARR SOUL                         ║
║                    Enhanced Book Downloader                  ║
║                     Powered by Soulseek                     ║
╚══════════════════════════════════════════════════════════════╝
    """

    # Use full width panel
    console.print(Panel(
        Text(banner_text, style="bold cyan"),
        box=box.DOUBLE,
        expand=True,
        width=console.width
    ))


def print_search_summary(query, results_count, search_type="main", status="completed"):
    """Print a formatted search summary using full terminal width"""
    if search_type == "fallback":
        icon = "🔄"
        style = "yellow"
        search_text = f"Fallback Search: {query}"
    else:
        icon = "🔍"
        style = "blue"
        search_text = f"Main Search: {query}"

    # Force full width by removing width constraints and using ratio
    table = Table(show_header=False, box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("", style=style, ratio=1, min_width=20)
    table.add_column("", style="white", ratio=4)

    table.add_row(f"{icon} Query:", search_text)

    if status == "searching":
        table.add_row("⏳ Status:", "Searching...")
    else:
        table.add_row("📊 Results:", f"{results_count} files found")

    console.print(table)

def print_directory_summary(username, directory_data):
    """Print a clean summary of directory contents using full width"""
    if isinstance(directory_data, list) and len(directory_data) > 0:
        dir_info = directory_data[0]
        file_count = dir_info.get('fileCount', 0)
        dir_name = dir_info.get('name', 'Unknown')
    elif isinstance(directory_data, dict):
        file_count = len(directory_data.get('files', []))
        dir_name = directory_data.get('name', 'Unknown')
    else:
        file_count = 0
        dir_name = 'Unknown'

    # Force full width
    table = Table(show_header=False, box=box.SIMPLE, expand=True, width=console.width)
    table.add_column("", style="cyan", ratio=1, min_width=20)
    table.add_column("", style="white", ratio=4)

    table.add_row("👤 User:", username)
    table.add_row("📁 Directory:", dir_name.split('\\')[-1])
    table.add_row("📄 Files:", f"{file_count} files")

    console.print(table)

def print_download_summary(downloads):
    """Print a formatted table of downloads using full terminal width"""
    if not downloads:
        console.print("❌ No downloads to process", style="red")
        return

    # Use the detected terminal width directly
    effective_width = TERMINAL_WIDTH

    table = Table(
        title="📥 Download Queue",
        box=box.ROUNDED,
        expand=False,  # Changed to False to prevent overflow
        width=effective_width,
        show_lines=False
    )

    # Calculate column widths based on effective width
    user_width = max(12, int(effective_width * 0.12))
    author_width = max(15, int(effective_width * 0.15))
    title_width = max(20, int(effective_width * 0.18))
    file_width = max(30, int(effective_width * 0.35))
    ratio_width = 8
    size_width = 10

    table.add_column("👤 User", style="cyan", width=user_width, no_wrap=True)
    table.add_column("👨‍💻 Author", style="green", width=author_width, no_wrap=True)
    table.add_column("📚 Title", style="yellow", width=title_width, no_wrap=True)
    table.add_column("📄 File", style="white", width=file_width, no_wrap=False)  # Allow wrapping for long filenames
    table.add_column("📊 Ratio", style="magenta", width=ratio_width, justify="center", no_wrap=True)
    table.add_column("💾 Size", style="blue", width=size_width, justify="right", no_wrap=True)

    for item in downloads:
        username = str(item.get('username', ''))
        author = str(item.get('author', ''))
        book = str(item.get('book', ''))
        file = str(item.get('filename', ''))
        match_ratio = item.get('match_ratio', '')

        # Truncate long text to fit columns
        if len(username) > user_width - 2:
            username = username[:user_width-5] + "..."
        if len(author) > author_width - 2:
            author = author[:author_width-5] + "..."
        if len(book) > title_width - 2:
            book = book[:title_width-5] + "..."

        if isinstance(match_ratio, float):
            match_ratio_str = f"{match_ratio:.3f}"
        else:
            match_ratio_str = str(match_ratio)

        size = item.get('size', 0)
        if isinstance(size, (int, float)):
            if size > 1e9:
                size_str = f"{size/1e9:.1f}GB"
            elif size > 1e6:
                size_str = f"{size/1e6:.1f}MB"
            elif size > 1e3:
                size_str = f"{size/1e3:.0f}KB"
            else:
                size_str = f"{size}B"
        else:
            size_str = str(size)

        table.add_row(username, author, book, file, match_ratio_str, size_str)

    console.print(table)

def print_import_summary(commands, grab_list):
    """Print a formatted table of import operations using full width"""
    if not commands:
        return

    effective_width = TERMINAL_WIDTH

    table = Table(
        title="📚 Import Operations",
        box=box.ROUNDED,
        expand=False,
        width=effective_width,
        show_lines=True
    )

    # Calculate proportional widths
    author_width = max(15, int(effective_width * 0.25))
    book_width = max(20, int(effective_width * 0.30))
    files_width = 8
    size_width = 12
    id_width = 12
    status_width = 10

    table.add_column("👤 Author", style="green", width=author_width, no_wrap=True)
    table.add_column("📚 Book", style="yellow", width=book_width, no_wrap=True)
    table.add_column("📄 Files", style="white", width=files_width, justify="center", no_wrap=True)
    table.add_column("💾 Total Size", style="blue", width=size_width, justify="right", no_wrap=True)
    table.add_column("🆔 Command ID", style="cyan", width=id_width, justify="center", no_wrap=True)
    table.add_column("📊 Status", style="white", width=status_width, justify="center", no_wrap=True)

    for command in commands:
        if 'body' in command and 'path' in command['body']:
            path = command['body']['path']
            folder_name = os.path.basename(path)
        else:
            folder_name = f"Task {command['id']}"

        author_name = "Unknown"
        book_title = "Unknown"
        file_count = 0
        total_size = 0

        for item in grab_list:
            item_dir = item.get('dir', '')
            item_author_sanitized = sanitize_folder_name(item.get('artist_name', ''))
            if item_dir == folder_name or item_author_sanitized == folder_name:
                if author_name == "Unknown":
                    author_name = item.get('artist_name', 'Unknown')
                book_title = item.get('title', 'Unknown')
                file_count += 1
                total_size += item.get('size', 0)

        # Truncate long text
        if len(author_name) > author_width - 2:
            author_name = author_name[:author_width-5] + "..."
        if len(book_title) > book_width - 2:
            book_title = book_title[:book_width-5] + "..."

        if total_size > 1e9:
            size_str = f"{total_size/1e9:.1f}GB"
        elif total_size > 1e6:
            size_str = f"{total_size/1e6:.1f}MB"
        elif total_size > 1e3:
            size_str = f"{total_size/1e3:.0f}KB"
        else:
            size_str = f"{total_size}B" if total_size > 0 else "0B"

        if file_count == 0:
            file_count = "?"
            size_str = "?"

        table.add_row(author_name, book_title, str(file_count), size_str, str(command['id']), "Queued")

    console.print(table)

def print_match_details(filename, ratio, username, filetype):
    """Print formatted match details using full width"""
    table = Table(show_header=False, box=box.SIMPLE, expand=True, width=console.width)
    table.add_column("", style="cyan", ratio=1, min_width=20)
    table.add_column("", style="white", ratio=4)

    table.add_row("📄 File:", filename)
    table.add_row("👤 User:", username)
    table.add_row("📊 Match Ratio:", f"{ratio:.3f}")
    table.add_row("📎 Type:", filetype)

    console.print(table, style="green")

def print_section_header(title, style="bold blue"):
    """Print a section header with styling using full width"""
    # Create a full-width header
    separator = "=" * console.width

    console.print(f"\n{separator}")
    console.print(f"  {title}", style=style)
    console.print(f"{separator}")

def album_match(target, slskd_tracks, username, filetype):
    """
    Match target book with available files, filtering by correct filetype.
    Enhanced to handle variations in punctuation, underscores, and additional text.
    """
    book_title = target['book']['title']
    artist_name = target['author']['authorName']
    best_match = 0.0
    current_match = None

    # Filter files by the correct filetype first
    filtered_tracks = []
    for slskd_track in slskd_tracks:
        if verify_filetype(slskd_track, filetype):
            filtered_tracks.append(slskd_track)

    if not filtered_tracks:
        logger.debug(f"No files found matching filetype: {filetype}")
        return None

    for slskd_track in filtered_tracks:
        slskd_filename = slskd_track['filename']
        logger.info(f"Checking ratio on {slskd_filename} vs wanted {book_title} - {artist_name}.{filetype.split(' ')[0]}")

        # First, check if this looks like a very good match based on title containment
        title_bonus_value = 0.0  # Changed variable name to avoid confusion
        if title_contained_in_filename(book_title, slskd_filename):
            title_bonus_value = title_bonus  # Use the global config value
            logger.info(f"Title containment bonus applied: +{title_bonus_value}")

        # Try multiple filename patterns for matching
        patterns_to_try = [
            f"{book_title} - {artist_name}.{filetype.split(' ')[0]}",
            f"{artist_name} - {book_title}.{filetype.split(' ')[0]}",
            f"{book_title}.{filetype.split(' ')[0]}",
            f"{artist_name} {book_title}.{filetype.split(' ')[0]}",
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
            ratio = check_ratio(" ", ratio, pattern, slskd_filename)
            max_ratio = max(max_ratio, ratio)
            ratio = check_ratio("_", ratio, pattern, slskd_filename)
            max_ratio = max(max_ratio, ratio)

        # Apply title bonus if applicable
        final_ratio = max_ratio + title_bonus_value

        if final_ratio > best_match:
            logger.info(f"New best match found! Ratio: {max_ratio:.3f} + Title bonus: {title_bonus_value:.3f} = {final_ratio:.3f}")
            best_match = final_ratio
            current_match = slskd_track
        else:
            logger.info(f"Ratio: {max_ratio:.3f} + Title bonus: {title_bonus_value:.3f} = {final_ratio:.3f} (not better than current best: {best_match:.3f})")

    if (current_match != None) and (username not in ignored_users) and (best_match >= minimum_match_ratio):
        logger.info("SUCCESSFUL MATCH")
        print_match_details(current_match['filename'], best_match, username, filetype)
        logger.info("-------------------")
        return current_match

    return None

def normalize_for_matching(text):
    """Normalize text for better matching by handling common variations"""
    import re
    # Convert to lowercase
    text = text.lower()
    # Replace underscores with spaces
    text = text.replace('_', ' ')
    # Remove common punctuation that might vary
    text = re.sub(r'[^\w\s]', ' ', text)
    # Normalize multiple spaces to single space
    text = re.sub(r'\s+', ' ', text)
    # Strip whitespace
    return text.strip()

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

def check_ratio(separator, ratio, lidarr_filename, slskd_filename):
    if ratio < minimum_match_ratio:
        if separator != "":
            lidarr_filename_word_count = len(lidarr_filename.split()) * -1
            truncated_slskd_filename = " ".join(slskd_filename.split(separator)[lidarr_filename_word_count:])
            ratio = difflib.SequenceMatcher(None, lidarr_filename, truncated_slskd_filename).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, lidarr_filename, slskd_filename).ratio()
        return ratio
    return ratio

def album_track_num(directory):
    files = directory['files']
    allowed_filetypes_no_attributes = [item.split(" ")[0] for item in allowed_filetypes]
    count = 0
    index = -1
    filetype = ""

    for file in files:
        if file['filename'].split(".")[-1] in allowed_filetypes_no_attributes:
            new_index = allowed_filetypes_no_attributes.index(file['filename'].split(".")[-1])
            if index == -1:
                index = new_index
                filetype = allowed_filetypes_no_attributes[index]
            elif new_index != index:
                filetype = ""
                break
            count += 1

    return_data = {
        "count": count,
        "filetype": filetype
    }

    return return_data

def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', '', folder_name)
    return valid_characters.strip()

def cancel_and_delete(delete_dir, username, files):
    for file in files:
        slskd.transfers.cancel_download(username = username, id = file['id'])

    os.chdir(slskd_download_dir)
    if os.path.exists(delete_dir):
        shutil.rmtree(delete_dir)

def release_trackcount_mode(releases):
    track_count = {}
    for release in releases:
        trackcount = release['trackCount']
        if trackcount in track_count:
            track_count[trackcount] += 1
        else:
            track_count[trackcount] = 1

    most_common_trackcount = None
    max_count = 0
    for trackcount, count in track_count.items():
        if count > max_count:
            max_count = count
            most_common_trackcount = trackcount

    return most_common_trackcount

def choose_release(artist_name, releases):
    most_common_trackcount = release_trackcount_mode(releases)

    for release in releases:
        country = release['country'][0] if release['country'] else None
        if release['format'][1] == 'x' and allow_multi_disc:
            format_accepted = release['format'].split("x", 1)[1] in accepted_formats
        else:
            format_accepted = release['format'] in accepted_formats

        if use_most_common_tracknum:
            if release['trackCount'] == most_common_trackcount:
                track_count_bool = True
            else:
                track_count_bool = False
        else:
            track_count_bool = True

        if (country in accepted_countries
            and format_accepted
            and release['status'] == "Official"
            and track_count_bool):
            logger.info(", ".join([
                f"Selected release for {artist_name}: {release['status']}",
                str(country),
                release['format'],
                f"Mediums: {release['mediumCount']}",
                f"Tracks: {release['trackCount']}",
                f"ID: {release['id']}",
            ]))
            return release

    if use_most_common_tracknum:
        for release in releases:
            if release['trackCount'] == most_common_trackcount:
                default_release = release
    else:
        default_release = releases[0]

    return default_release

def verify_filetype(file,allowed_filetype):
    current_filetype = file['filename'].split(".")[-1].lower()
    logger.debug(f"Current file type: {current_filetype}")
    if current_filetype == allowed_filetype.split(" ")[0]:
        return True
    else:
        return False

def check_for_match(dir_cache, search_cache, target, allowed_filetype):
    """
    Check for matching files in the directory cache.

    Args:
        dir_cache: Dictionary containing cached directory information
        search_cache: Dictionary containing cached search results
        target: Target book/author information
        allowed_filetype: File type to search for (e.g., 'epub', 'pdf')

    Returns:
        Tuple: (found, username, directory, file_dir, file) or (False, "", {}, "", None)
    """
    for username in dir_cache:
        if not allowed_filetype in dir_cache[username]:
            continue
        logger.info(f"Parsing result from user: {username}")

        for file_dir in dir_cache[username][allowed_filetype]:
            if username not in search_cache:
                logger.info(f"Add user to cache: {username}")
                search_cache[username] = {}

            if file_dir not in search_cache[username]:
                logger.info(f"Cache miss user: {username} folder: {file_dir}")
                try:
                    directory = slskd.users.directory(username=username, directory=file_dir)

                    # Show clean directory summary instead of raw data
                    print_directory_summary(username, directory)

                    # Fix: Handle both list and dict return types from SLSKD API
                    if isinstance(directory, list):
                        # If it's a list, extract files from the first directory object and preserve name
                        if len(directory) > 0 and isinstance(directory[0], dict) and 'files' in directory[0]:
                            logger.info("Converting list to dictionary format - extracting files from directory object")
                            # Preserve the original directory name for later matching
                            directory = {
                                'files': directory[0]['files'],
                                'name': directory[0]['name']
                            }
                        else:
                            logger.warning(f"Unexpected list structure from user: {username}, folder: {file_dir}")
                            continue
                    elif not isinstance(directory, dict) or 'files' not in directory:
                        # If it's not a dict or doesn't have 'files' key, skip
                        logger.warning(f"Unexpected directory structure from user: {username}, folder: {file_dir}")
                        continue

                except Exception as e:
                    logger.error(f"Error getting directory from user {username}: {e}")
                    continue

                search_cache[username][file_dir] = directory
            else:
                logger.info(f"Pulling from cache: {username} folder: {file_dir}")
                directory = copy.deepcopy(search_cache[username][file_dir])

            result = album_match(target, directory['files'], username, allowed_filetype)
            if result != None:
                return True, username, directory, file_dir, result
            else:
                continue

    return False, "", {}, "", None


def gen_allowed_filetypes(qprofile):
    allowed_filetypes = []
    for item in qprofile['items']:
        if item['allowed']:
            allowed_type = item['quality']['name'].lower()
            allowed_filetypes.append(allowed_type)
    allowed_filetypes.reverse()
    return allowed_filetypes

def search_and_download(grab_list, target, retry_list):
    book = target['book']
    author = target['author']
    qprofile = target['filetypes']
    artist_name = author['authorName']
    artist_id = author['id']
    album_id = book['id']
    album_title = book['title']
    allowed_filetypes = gen_allowed_filetypes(qprofile)

    if is_blacklisted(album_title):
        return False

    # Construct query with proper " - " separator between author and title
    query = f"{artist_name} - {album_title}"

    # Display initial search status
    search_table = Table(show_header=False, box=box.ROUNDED)
    search_table.add_column("Field", style="cyan", width=30)
    search_table.add_column("Value", style="white")

    search_table.add_row("🔍 Query:", f"Main Search: {artist_name} - {album_title}")
    search_table.add_row("⏳ Status:", "Searching...")

    console.print(search_table)

    # Perform initial search with connection handling
    search = safe_slskd_call(
        slskd.searches.search_text,
        searchText=query,
        searchTimeout=config.getint('Search Settings', 'search_timeout', fallback=5000),
        filterResponses=True,
        maximumPeerQueueLength=config.getint('Search Settings', 'maximum_peer_queue', fallback=50),
        minimumPeerUploadSpeed=config.getint('Search Settings', 'minimum_peer_upload_speed', fallback=0)
    )

    if search is None:
        logger.error(f"❌ Failed to start search for: {query}")
        return False

    time.sleep(10)

    while True:
        state_result = safe_slskd_call(slskd.searches.state, search['id'], False)
        if state_result is None:
            logger.error(f"❌ Lost connection while monitoring search: {query}")
            return False

        state = state_result['state']
        if state != 'InProgress':
            break
        time.sleep(1)

    search_results = safe_slskd_call(slskd.searches.search_responses, search['id'])
    if search_results is None:
        logger.error(f"❌ Failed to get search results for: {query}")
        return False

    print_search_summary(query, len(search_results), "main", "completed")

    # Handle fallback search if needed
    if len(search_results) == 0 and ":" in album_title:
        main_title = album_title.split(":")[0].strip()
        fallback_query = f"{artist_name} - {main_title}"
        logger.info(f"No results found for full title. Trying fallback search with main title: {fallback_query}")

        if delete_searches:
            slskd.searches.delete(search['id'])

        print_search_summary(fallback_query, 0, "fallback", "searching")

        search = slskd.searches.search_text(
            searchText=fallback_query,
            searchTimeout=config.getint('Search Settings', 'search_timeout', fallback=5000),
            filterResponses=True,
            maximumPeerQueueLength=config.getint('Search Settings', 'maximum_peer_queue', fallback=50),
            minimumPeerUploadSpeed=config.getint('Search Settings', 'minimum_peer_upload_speed', fallback=0)
        )

        time.sleep(10)

        while True:
            state = slskd.searches.state(search['id'], False)['state']
            if state != 'InProgress':
                break
            time.sleep(1)

        search_results = slskd.searches.search_responses(search['id'])
        print_search_summary(fallback_query, len(search_results), "fallback", "completed")

    # Build directory cache for all users and file types
    dir_cache = {}
    search_cache = {}

    for result in search_results:
        username = result['username']
        if username not in dir_cache:
            dir_cache[username] = {}

        logger.info(f"Truncating directory count of user: {username}")

        init_files = result['files']
        for file in init_files:
            file_dir = file['filename'].rsplit('\\', 1)[0]
            for allowed_filetype in allowed_filetypes:
                if verify_filetype(file, allowed_filetype):
                    if allowed_filetype not in dir_cache[username]:
                        dir_cache[username][allowed_filetype] = []
                    if file_dir not in dir_cache[username][allowed_filetype]:
                        dir_cache[username][allowed_filetype].append(file_dir)

    # Update the table to show what filetypes we're searching for
    search_table = Table(show_header=False, box=box.ROUNDED)
    search_table.add_column("Field", style="cyan", width=30)
    search_table.add_column("Value", style="white")

    search_table.add_row("🔍 Query:", f"Main Search: {artist_name} - {album_title}")
    search_table.add_row("📁 File Types:", ", ".join(allowed_filetypes))
    search_table.add_row("⏳ Status:", "Searching across all file types...")

    console.print(search_table)

    # NEW: Collect ALL good matches instead of stopping at first
    all_matches = []
    for allowed_filetype in allowed_filetypes:
        # Remove the individual logging line here
        # logger.info(f"ℹ️  Searching for matches with selected attributes: {allowed_filetype}")

        # Check ALL users for this filetype
        for username in dir_cache:
            if allowed_filetype not in dir_cache[username]:
                continue

            logger.info(f"Parsing result from user: {username}")

            for file_dir in dir_cache[username][allowed_filetype]:
                if username not in search_cache:
                    logger.info(f"Add user to cache: {username}")
                    search_cache[username] = {}

                if file_dir not in search_cache[username]:
                    logger.info(f"Cache miss user: {username} folder: {file_dir}")
                    try:
                        directory = slskd.users.directory(username=username, directory=file_dir)
                        print_directory_summary(username, directory)

                        # Handle both list and dict return types from SLSKD API
                        if isinstance(directory, list):
                            if len(directory) > 0 and isinstance(directory[0], dict) and 'files' in directory[0]:
                                logger.info("Converting list to dictionary format - extracting files from directory object")
                                directory = {
                                    'files': directory[0]['files'],
                                    'name': directory[0]['name']
                                }
                            else:
                                logger.warning(f"Unexpected list structure from user: {username}, folder: {file_dir}")
                                continue
                        elif not isinstance(directory, dict) or 'files' not in directory:
                            logger.warning(f"Unexpected directory structure from user: {username}, folder: {file_dir}")
                            continue

                    except Exception as e:
                        logger.error(f"Error getting directory from user {username}: {e}")
                        continue

                    search_cache[username][file_dir] = directory
                else:
                    logger.info(f"Pulling from cache: {username} folder: {file_dir}")
                    directory = copy.deepcopy(search_cache[username][file_dir])

                # Check for matches in this directory
                result = album_match(target, directory['files'], username, allowed_filetype)
                if result != None:
                    # FIXED: Store the actual match ratio from album_match
                    actual_match_ratio = get_match_ratio(target, result, username, allowed_filetype)

                    match_info = {
                        'username': username,
                        'directory': directory,
                        'file_dir': file_dir,
                        'file': result,
                        'filetype': allowed_filetype,
                        'match_ratio': actual_match_ratio  # Use consistent calculation
                    }
                    all_matches.append(match_info)


    # Display final results
    results_table = Table(show_header=False, box=box.ROUNDED)
    results_table.add_column("Field", style="cyan", width=30)
    results_table.add_column("Value", style="white")

    results_table.add_row("🔍 Query:", f"Main Search: {artist_name} - {album_title}")
    results_table.add_row("📁 File Types:", ", ".join(allowed_filetypes))

    if all_matches:
        results_table.add_row("📊 Results:", f"{len(all_matches)} files found")
        results_table.add_row("✅ Status:", "Matches found, proceeding to download...")
    else:
        results_table.add_row("📊 Results:", "0 files found")
        results_table.add_row("❌ Status:", "No matches found")

    console.print(results_table)

    # Filter and sort matches by quality
    if not all_matches:
        if delete_searches:
            slskd.searches.delete(search['id'])
        logger.error(f"🚨 Failed to grab album: {album_title} for artist: {artist_name}")
        return False

    # Sort by match ratio (highest first) and download all good matches
    all_matches.sort(key=lambda x: x['match_ratio'], reverse=True)
    good_matches = [match for match in all_matches if match['match_ratio'] >= minimum_match_ratio]

    logger.info(f"ℹ️  Found {len(good_matches)} good matches out of {len(all_matches)} total matches")

    # Download all good matches
    downloaded_any = False
    for match in good_matches:
        try:
            if download_album(target, match['username'], match['file_dir'], match['directory'], retry_list, grab_list, match['file'], match['filetype']): # Pass the filetype
                downloaded_any = True
                logger.info(f"Successfully queued download from {match['username']}: {match['file']['filename']}")
            else:
                logger.warning(f"Failed to queue download from {match['username']}: {match['file']['filename']}")
        except Exception as e:
            logger.error(f"Error downloading from {match['username']}: {e}")
            continue

    if delete_searches:
        slskd.searches.delete(search['id'])

    return downloaded_any

def get_match_ratio(target, file, username, filetype):
    """
    Calculate match ratio using the EXACT same algorithm as album_match.
    This ensures consistency between search and download phases.
    """
    book_title = target['book']['title']
    artist_name = target['author']['authorName']
    filename = file['filename']

    logger.debug(f"Calculating ratio for {filename} vs wanted {book_title} - {artist_name}.{filetype.split(' ')[0]}")

    # Apply title containment bonus (same as album_match)
    title_bonus_value = 0.0
    if title_contained_in_filename(book_title, filename):
        title_bonus_value = title_bonus
        logger.debug(f"Title containment bonus applied: +{title_bonus_value}")

    # Try multiple filename patterns (same as album_match)
    patterns_to_try = [
        f"{book_title} - {artist_name}.{filetype.split(' ')[0]}",
        f"{artist_name} - {book_title}.{filetype.split(' ')[0]}",
        f"{book_title}.{filetype.split(' ')[0]}",
        f"{artist_name} {book_title}.{filetype.split(' ')[0]}",
    ]

    max_ratio = 0.0
    for pattern in patterns_to_try:
        # Direct ratio
        ratio = difflib.SequenceMatcher(None, pattern, filename).ratio()
        max_ratio = max(max_ratio, ratio)

        # Try with normalized strings for better matching
        normalized_pattern = normalize_for_matching(pattern)
        normalized_filename = normalize_for_matching(filename)
        normalized_ratio = difflib.SequenceMatcher(None, normalized_pattern, normalized_filename).ratio()
        max_ratio = max(max_ratio, normalized_ratio)

        # Try with different separators (same as album_match)
        ratio = check_ratio(" ", ratio, pattern, filename)
        max_ratio = max(max_ratio, ratio)
        ratio = check_ratio("_", ratio, pattern, filename)
        max_ratio = max(max_ratio, ratio)

    # Return final ratio with title bonus (matches album_match exactly)
    final_ratio = max_ratio + title_bonus_value
    logger.debug(f"Final calculated ratio: {max_ratio:.3f} + {title_bonus_value:.3f} = {final_ratio:.3f}")

    return final_ratio


def download_album(target, username, file_dir, directory, retry_list, grab_list, file, allowed_filetype):
    # Check for duplicates before adding to grab_list
    file_size = file.get('size', 0)

   # FIXED: Calculate match ratio consistently
    calculated_match_ratio = get_match_ratio(target, file, username, allowed_filetype)

    # Create temporary folder data to check duplicates
    temp_folder_data = {
        "artist_name": target['author']['authorName'],
        "title": target['book']['title'],
        'bookId': target['book']['id'],
        "dir": file_dir.split("\\")[-1],
        "username": username,
        "directory": directory,
        "filename": file['filename'],
        "size": file_size,
        "match_ratio": calculated_match_ratio  # Use calculated ratio
    }

    # Check for duplicates
    if is_duplicate_file(temp_folder_data, grab_list):
        logger.info(f"⚠️ Skipping duplicate file: {file['filename']} (size: {file_size} bytes)")
        return True

    directory['files'] = [file]
    filename = file['filename']

    for i in range(0, len(directory['files'])):
        directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']

    folder_data = {
        "artist_name": target['author']['authorName'],
        "title": target['book']['title'],
        'bookId': target['book']['id'],
        "dir": file_dir.split("\\")[-1],
        "username": username,
        "directory": directory,
        "filename": filename,
        "size": file_size,
        "match_ratio": calculated_match_ratio  # Use same calculated ratio
    }

    grab_list.append(folder_data)

    try:
        slskd.transfers.enqueue(username = username, files = directory['files'])
        logger.info(f"Adding {username} to retry list")
        retry_list[username] = {}
        for file in directory['files']:
            logger.info(f"Adding {file['filename']} to retry list")
            retry_list[username][file['filename']] = 0
        return True
    except Exception as e:
        logger.warning(f"Exception {e}")
        logger.warning(f"Error enqueueing tracks! Adding {username} to ignored users list.")
        downloads = slskd.transfers.get_downloads(username)
        for cancel_directory in downloads["directories"]:
            if cancel_directory["directory"] == directory["name"]:
                cancel_and_delete(file_dir.split("\\")[-1], username, cancel_directory["files"])
        grab_list.remove(folder_data)
        ignored_users.append(username)
        return False

def is_blacklisted(title: str) -> bool:
    blacklist = config.get('Search Settings', 'title_blacklist', fallback='').lower().split(",")
    for word in blacklist:
        if word != '' and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False

def is_duplicate_file(new_file, grab_list):
    """Check if a file with same size already exists in grab_list"""
    new_size = new_file.get('size', 0)
    new_filename = new_file.get('filename', '')

    for existing_item in grab_list:
        existing_size = existing_item.get('size', 0)
        existing_filename = existing_item.get('filename', '')

        # Check if same size and similar filename (likely same file)
        if (new_size == existing_size and new_size > 0 and
            os.path.splitext(new_filename)[0].lower() == os.path.splitext(existing_filename)[0].lower()):
            return True

    return False

def grab_most_wanted(download_targets):
    grab_list = []
    failed_download = 0
    success = False
    retry_list = {}

    print_section_header("🎯 STARTING SEARCH PHASE")

    for target in download_targets:
        book = target['book']
        author = target['author']
        artist_name = author['authorName']
        success = search_and_download(grab_list, target, retry_list)

        if not success:
            if remove_wanted_on_failure:
                logger.error(f"Failed to grab album: {book['title']} for artist: {artist_name}."
                + ' Failed album removed from wanted list and added to "failure_list.txt"')
                book['monitored'] = False
                edition = readarr.get_edition(book['id'])
                readarr.upd_book(book=book, editions=edition)
                current_datetime = datetime.now()
                current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")
                failure_string = current_datetime_str + " - " + artist_name + ", " + book['title'] + "\n"
                with open(failure_file_path, "a") as file:
                    file.write(failure_string)
            else:
                pass
            failed_download += 1

    # CORRECTED DOWNLOAD MONITORING PHASE
    print_section_header("📥 DOWNLOAD MONITORING PHASE")

    if len(grab_list) > 0:
        # Create download summary for display
        downloads_for_display = []
        for item in grab_list:
            author = item.get('artist_name', '')
            book = item.get('title', '')
            username = item.get('username', '')
            filename = item.get('filename', '')
            match_ratio = item.get('match_ratio', '')  # Ensure you stored it in grab_list
            # Get file size safely
            dir_name = item.get('dir', '')
            file_path = os.path.join(dir_name, filename)
            try:
                size = os.path.getsize(file_path)
            except Exception:
                size = 0

            downloads_for_display.append({
                'username': username,
                'author': author,
                'book': book,
                'filename': filename,
                'match_ratio': match_ratio,
                'size': size,
            })

        # Show download queue table
        print_download_summary(downloads_for_display)

        logger.info("ℹ️ Waiting for downloads... monitor at:")
        logger.info(f"   {slskd_host_url}/downloads")

        # PROPER DOWNLOAD MONITORING with improved error handling
        time_count = 0
        previous_total = sys.maxsize

        while True:
            unfinished = 0
            total_remaining = 0
            files_were_retried = False

            for artist_folder in list(grab_list):
                username, dir = artist_folder['username'], artist_folder['directory']

                try:
                    downloads = slskd.transfers.get_downloads(username)
                    user_directory_found = False

                    for directory in downloads["directories"]:
                        if directory["directory"] == dir["name"]:
                            user_directory_found = True

                            for file in directory['files']:
                                total_remaining += file['bytesRemaining']

                            # Handle errored files with improved retry logic
                            errored_files = []
                            files_retried_this_iteration = []

                            for file in directory["files"]:
                                if file["state"] == 'Completed, Errored':
                                    logger.info(f"File: {file['filename']} has an error.")

                                    # Check retry count for this specific file
                                    if username in retry_list and file['filename'] in retry_list[username]:
                                        retry_list[username][file['filename']] += 1

                                        if retry_list[username][file['filename']] > 2:
                                            logger.info(f"Too many retries: {file['filename']}")
                                            errored_files.append(file)
                                        else:
                                            logger.info(f"Retry file: {file['filename']}")
                                            try:
                                                # Create a new file object for retry
                                                retry_file = {
                                                    'filename': file['filename'],
                                                    'size': file.get('size', 0)
                                                }
                                                slskd.transfers.enqueue(username=username, files=[retry_file])
                                                files_retried_this_iteration.append(file['filename'])
                                                files_were_retried = True
                                            except Exception as retry_error:
                                                logger.error(f"Failed to retry file {file['filename']}: {retry_error}")
                                                errored_files.append(file)
                                    else:
                                        # File not in retry list, add it and retry
                                        if username not in retry_list:
                                            retry_list[username] = {}
                                        retry_list[username][file['filename']] = 1

                                        logger.info(f"Retry file: {file['filename']}")
                                        try:
                                            retry_file = {
                                                'filename': file['filename'],
                                                'size': file.get('size', 0)
                                            }
                                            slskd.transfers.enqueue(username=username, files=[retry_file])
                                            files_retried_this_iteration.append(file['filename'])
                                            files_were_retried = True
                                        except Exception as retry_error:
                                            logger.error(f"Failed to retry file {file['filename']}: {retry_error}")
                                            errored_files.append(file)

                                elif file["state"] in [
                                    'Completed, Cancelled',
                                    'Completed, TimedOut',
                                    'Completed, Rejected',
                                ]:
                                    errored_files.append(file)

                            # Count pending files (exclude retried files from pending count)
                            pending_files = []
                            for file in directory["files"]:
                                if file['filename'] in files_retried_this_iteration:
                                    # File was just retried, don't count as pending yet
                                    continue
                                elif not ('Completed' in file["state"] and file["state"] not in ['Completed, Errored']):
                                    pending_files.append(file)

                            # Handle failed downloads (only if errors can't be retried)
                            if len(errored_files) > 0:
                                logger.error(f"FAILED: Username: {username} Directory: {dir['name']}")
                                logger.error(f"Failed files: {[f['filename'] for f in errored_files]}")

                                cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                                grab_list.remove(artist_folder)

                                # Clean up retry list for this user/directory
                                if username in retry_list:
                                    for file in directory['files']:
                                        if file['filename'] in retry_list[username]:
                                            del retry_list[username][file['filename']]
                                    if len(retry_list[username]) <= 0:
                                        del retry_list[username]

                            elif len(pending_files) > 0:
                                unfinished += 1

                            break  # Found the directory, no need to continue

                    if not user_directory_found:
                        # Directory not found in downloads, might be completed or cancelled
                        logger.info(f"Directory not found in downloads for {username}, assuming completed")
                        # Don't increment unfinished for this case

                except Exception as e:
                    logger.error(f"❌ Error checking downloads for user {username}: {e}")

                    # Try to recover connection
                    if "Connection refused" in str(e).lower() or "connectionerror" in str(type(e).__name__).lower():
                        logger.warning("🔄 Attempting SLSKD connection recovery...")
                        if check_slskd_recovery():
                            continue  # Retry the current operation
                        else:
                            logger.error("💔 Cannot recover SLSKD connection, continuing with remaining operations")

                    unfinished += 1

            # If files were retried, wait before checking again
            if files_were_retried:
                logger.info("Files were retried, waiting before next check...")
                time.sleep(5)
                continue

            # Check if all downloads are complete
            if unfinished == 0:
                logger.info("🎉 All tracks finished downloading!")
                time.sleep(5)
                retry_list = {}
                break

            # Handle stalled downloads
            if previous_total > total_remaining:
                previous_total = total_remaining
                time_count = 0
            else:
                time_count += 10

            if time_count > stalled_timeout:
                logger.info("Stall timeout reached! Removing stuck downloads...")
                for artist_folder in list(grab_list):
                    username, dir = artist_folder['username'], artist_folder['directory']
                    try:
                        downloads = slskd.transfers.get_downloads(username)
                        for directory in downloads["directories"]:
                            if directory["directory"] == dir["name"]:
                                pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]
                                if len(pending_files) > 0:
                                    logger.error(f"Removing Stalled Download: Username: {username} Directory: {dir['name']}")
                                    cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                                    grab_list.remove(artist_folder)
                    except Exception as e:
                        logger.error(f"Error handling stalled download for {username}: {e}")

                logger.info("🎉 All tracks finished downloading!")
                time.sleep(5)
                break

            # Wait before next check
            time.sleep(10)

    else:
        logger.warning("⚠️ No downloads were queued, proceeding to import phase")

    # NOW PROCEED TO IMPORT PHASE
    print_section_header("📚 METADATA VALIDATION & IMPORT PHASE")

    # Check if sync is disabled first
    if lidarr_disable_sync:
        logger.warning("⚠️ Readarr sync is disabled in config. Skipping import phase.")
        logger.info(f"Files downloaded but not imported. Check download directory: {slskd_download_dir}")
        return failed_download

    os.chdir(slskd_download_dir)
    logger.info(f"📁 Changed to download directory: {slskd_download_dir}")

    commands = []
    grab_list.sort(key=operator.itemgetter('artist_name'))
    failed_imports = []
    processed_files = set()  # Track processed files to avoid duplicates
    processed_files_status = {}

    for artist_folder in grab_list:
        try:
            artist_name = artist_folder['artist_name']
            artist_name_sanitized = sanitize_folder_name(artist_name)
            folder = artist_folder['dir']
            filename = artist_folder['filename']
            book_title = artist_folder['title']
            book_id = artist_folder['bookId']

            # Create unique identifier for this file to avoid duplicate processing
            file_identifier = f"{artist_name_sanitized}/{filename}"
            if file_identifier in processed_files:
                logger.info(f"ℹ️ File already processed, skipping: {filename}")
                continue
            processed_files.add(file_identifier)

            logger.info(f"🔍 Processing file: {filename} for book: {book_title}")
            logger.info(f"📂 Source folder: {folder}")
            logger.info(f"👤 Target author folder: {artist_name_sanitized}")

            # Check if source file exists
            source_file_path = os.path.join(folder, filename)
            if not os.path.exists(source_file_path):
                logger.error(f"❌ Source file not found: {source_file_path}")
                failed_imports.append((folder, filename, artist_name_sanitized, f"Source file not found: {source_file_path}"))
                continue

            logger.info(f"✅ Source file exists: {source_file_path}")

            extension = filename.split('.')[-1].lower()
            match = False

            # Enhanced metadata validation with better error handling
            if extension in ['azw3', 'mobi']:
                try:
                    logger.info(f"📖 Reading MOBI/AZW3 metadata from: {source_file_path}")
                    metadata = MobiHeader(source_file_path)
                    isbn = metadata.get_exth_value_by_id(104)
                    if isbn is not None:
                        logger.info(f"📚 Found ISBN in metadata: {isbn}")
                        try:
                            book_lookup = readarr.lookup(term=f"isbn:{str(isbn).strip()}")
                            if book_lookup and len(book_lookup) > 0:
                                book_to_test = book_lookup[0]['id']
                                if book_to_test == book_id:
                                    logger.info("✅ ISBN matches book ID - validation passed")
                                    match = True
                                else:
                                    logger.warning(f"⚠️ ISBN mismatch: expected {book_id}, got {book_to_test}")
                                    match = False
                            else:
                                logger.warning(f"⚠️ No book found for ISBN {isbn}, allowing import")
                                match = True
                        except Exception as e:
                            logger.warning(f"⚠️ Error looking up ISBN {isbn}: {e}, allowing import")
                            match = True
                    else:
                        logger.info("ℹ️ No ISBN found in metadata, allowing import")
                        match = True
                except Exception as e:
                    logger.error(f"❌ Error reading MOBI/AZW3 metadata: {e}")
                    logger.info("ℹ️ Allowing import despite metadata error")
                    match = True

            elif extension == 'epub':
                try:
                    import re  # Add this line to fix the error
                    logger.info(f"📖 Reading EPUB metadata from: {source_file_path}")
                    metadata = ebookmeta.get_metadata(source_file_path)
                    title = metadata.title
                    if title:
                        logger.info(f"📚 Found title in metadata: '{title}'")
                        logger.info(f"🎯 Expected title: '{book_title}'")

                        # Enhanced title matching
                        diff = difflib.SequenceMatcher(None, title, book_title).ratio()
                        logger.info(f"📊 Exact title match ratio: {diff:.3f}")

                        normalized_title = re.sub(r'[^\w\s]', '', title.lower())
                        normalized_book_title = re.sub(r'[^\w\s]', '', book_title.lower())
                        normalized_diff = difflib.SequenceMatcher(None, normalized_title, normalized_book_title).ratio()
                        logger.info(f"📊 Normalized title match ratio: {normalized_diff:.3f}")

                        title_words = set(title.lower().split())
                        book_title_words = set(book_title.lower().split())
                        word_intersection = len(title_words.intersection(book_title_words))
                        word_union = len(title_words.union(book_title_words))
                        word_similarity = word_intersection / word_union if word_union > 0 else 0
                        logger.info(f"📊 Word-based similarity: {word_similarity:.3f}")

                        if diff > 0.8 or normalized_diff > 0.85 or word_similarity > 0.7:
                            logger.info("✅ Title validation passed")
                            match = True
                        else:
                            logger.warning(f"⚠️ Title validation failed - insufficient similarity")
                            match = False
                    else:
                        logger.warning("⚠️ No title found in EPUB metadata, allowing import")
                        match = True
                except Exception as e:
                    logger.error(f"❌ Error reading EPUB metadata: {e}")
                    logger.info("ℹ️ Allowing import despite metadata error")
                    match = True
            else:
                logger.info(f"ℹ️ File type {extension} - skipping metadata validation")
                match = True

            if match:
                logger.info("✅ Metadata validation passed - proceeding with file organization")
                processed_files_status[filename] = 'moved_to_import'

                # Create target directory
                if not os.path.exists(artist_name_sanitized):
                    logger.info(f"📁 Creating author directory: {artist_name_sanitized}")
                    try:
                        os.makedirs(artist_name_sanitized, exist_ok=True)
                    except Exception as e:
                        logger.error(f"❌ Failed to create directory {artist_name_sanitized}: {e}")
                        failed_imports.append((folder, filename, artist_name_sanitized, f"Failed to create directory: {e}"))
                        continue

                # Handle target file path
                target_file_path = os.path.join(artist_name_sanitized, filename)
                if os.path.exists(target_file_path):
                    logger.warning(f"⚠️ Target file already exists: {target_file_path}")
                    # Check if files are identical
                    try:
                        if filecmp.cmp(source_file_path, target_file_path, shallow=False):
                            logger.info("ℹ️ Files are identical, keeping existing file for import")
                            os.remove(source_file_path)
                            # DON'T remove the directory yet - we need it for import
                            # Just mark that the file was processed successfully
                            processed_files_status[filename] = 'identical_file_kept'
                        else:
                            # Files are different, create unique name
                            base_name, ext = os.path.splitext(filename)
                            counter = 1
                            while os.path.exists(target_file_path):
                                new_filename = f"{base_name}_{counter}{ext}"
                                target_file_path = os.path.join(artist_name_sanitized, new_filename)
                                counter += 1
                            logger.info(f"📤 Moving file to unique name: {target_file_path}")
                            shutil.move(source_file_path, target_file_path)
                    except Exception as e:
                        logger.error(f"❌ Error handling existing file: {e}")
                        # Create unique name as fallback
                        base_name, ext = os.path.splitext(filename)
                        timestamp = str(int(time.time()))
                        new_filename = f"{base_name}_{timestamp}{ext}"
                        target_file_path = os.path.join(artist_name_sanitized, new_filename)
                        shutil.move(source_file_path, target_file_path)
                        logger.info(f"📤 Moved file with timestamp: {target_file_path}")
                else:
                    # Move file to target directory
                    try:
                        logger.info(f"📤 Moving file from {source_file_path} to {target_file_path}")
                        shutil.move(source_file_path, target_file_path)
                        logger.info("✅ File moved successfully")
                    except Exception as e:
                        logger.error(f"❌ Failed to move file: {e}")
                        failed_imports.append((folder, filename, artist_name_sanitized, f"Failed to move file: {e}"))
                        continue

                # MODIFIED: Only clean up empty source directory if no identical files were found
                try:
                    if os.path.exists(folder) and os.path.isdir(folder):
                        remaining_files = os.listdir(folder)
                        if not remaining_files:
                            logger.info(f"🗑️ Removing empty source directory: {folder}")
                            shutil.rmtree(folder)
                        else:
                            logger.info(f"ℹ️ Source directory not empty, keeping: {folder}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not remove source directory {folder}: {e}")

            else:
                logger.warning(f"❌ Metadata validation failed for {filename}")
                processed_files_status[filename] = 'validation_failed'
                failed_imports.append((folder, filename, artist_name_sanitized, "Metadata validation failed"))

        except Exception as e:
            logger.error(f"❌ Unexpected error processing {artist_folder.get('filename', 'unknown')}: {e}")
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            failed_imports.append((
                artist_folder.get('dir', 'unknown'),
                artist_folder.get('filename', 'unknown'),
                artist_folder.get('artist_name', 'unknown'),
                f"Unexpected error: {e}"
            ))

    # Enhanced cleanup of duplicate and empty directories
    cleanup_duplicate_directories()

    # Handle failed imports
    if failed_imports:
        logger.warning(f"⚠️ {len(failed_imports)} files failed validation/processing")
        for folder, filename, artist_name_sanitized, error_reason in failed_imports:
            logger.warning(f"❌ Failed: {filename} - Reason: {error_reason}")
            # DON'T move failed files yet - wait to see if any imports succeed

    # Get list of successfully processed author folders
    try:
        artist_folders = next(os.walk('.'))[1]
        artist_folders = [folder for folder in artist_folders if folder != 'failed_imports']
        logger.info(f"📂 Found {len(artist_folders)} author folders to import: {artist_folders}")
    except Exception as e:
        logger.error(f"❌ Error listing directories: {e}")
        artist_folders = []

    # Start Readarr import process
    if artist_folders:
        logger.info("🚀 Starting Readarr import commands...")
        for artist_folder in artist_folders:
            try:
                download_dir = os.path.join(lidarr_download_dir, artist_folder)
                logger.info(f"📚 Importing from: {download_dir}")
                command = readarr.post_command(name='DownloadedBooksScan', path=download_dir)
                commands.append(command)
                logger.info(f"✅ Import command created - ID: {command['id']} for folder: {artist_folder}")
            except Exception as e:
                logger.error(f"❌ Failed to create import command for {artist_folder}: {e}")
                logger.error(f"🔍 Traceback: {traceback.format_exc()}")

        if commands:
            print_import_summary(commands, grab_list)

            # Monitor import progress
            logger.info("⏳ Monitoring import progress...")
            while True:
                completed_count = 0
                for task in commands:
                    try:
                        current_task = readarr.get_command(task['id'])
                        if current_task['status'] in ['completed', 'failed']:
                            completed_count += 1
                    except Exception as e:
                        logger.error(f"❌ Error checking task {task['id']}: {e}")
                        completed_count += 1 # Count as completed to avoid infinite loop

                if completed_count == len(commands):
                    break
                time.sleep(2)

            # Enhanced results checking - get specific Readarr rejection details with full file paths
            logger.info("📊 Import Results:")
            successful_imports = []
            failed_readarr_imports = []
            any_successful_imports = False

            # Create a mapping of folders to their actual files for better logging
            folder_to_files = {}
            for item in grab_list:
                folder = item.get('dir', '')
                filename = item.get('filename', '')
                if folder not in folder_to_files:
                    folder_to_files[folder] = []
                folder_to_files[folder].append(filename)

            # Also map author directories to their files
            author_dir_files = {}
            for artist_folder in artist_folders:
                try:
                    if os.path.exists(artist_folder) and os.path.isdir(artist_folder):
                        files_in_dir = os.listdir(artist_folder)
                        book_files = [f for f in files_in_dir if f.lower().endswith(('.epub', '.pdf', '.mobi', '.azw3', '.azw'))]
                        author_dir_files[artist_folder] = book_files
                except:
                    author_dir_files[artist_folder] = []

            for task in commands:
                try:
                    current_task = readarr.get_command(task['id'])
                    status = current_task.get('status', 'unknown')

                    # Get import folder path
                    if 'body' in current_task and 'path' in current_task['body']:
                        import_folder = current_task['body']['path']
                        folder_name = os.path.basename(import_folder)
                    else:
                        import_folder = None
                        folder_name = f"Task {task['id']}"

                    message = current_task.get('message', '')

                    # Parse import count from message
                    import re
                    import_match = re.search(r'Importing (\d+) files?', message)
                    imported_count = int(import_match.group(1)) if import_match else 0

                    # Get files associated with this folder for better logging
                    associated_files = []
                    if folder_name in folder_to_files:
                        associated_files = folder_to_files[folder_name]
                    elif folder_name in author_dir_files:
                        associated_files = author_dir_files[folder_name]

                    if status == 'completed':
                        # Create detailed file path information
                        file_info = ""
                        if len(associated_files) == 1:
                            file_info = f" [{folder_name}/{associated_files[0]}]"
                        elif len(associated_files) > 1:
                            file_info = f" [{folder_name}/ with {len(associated_files)} files]"
                        else:
                            file_info = f" [{folder_name}/]"

                        logger.info(f"📋 {folder_name}{file_info}: Readarr command completed")
                        logger.info(f"💬 Readarr response: {message}")

                        if imported_count > 0:
                            # Log successful imports with full file information
                            success_msg = f"✅ {folder_name}: Import completed successfully ({imported_count} files imported)"
                            if len(associated_files) == 1:
                                success_msg += f" - File: {associated_files[0]}"
                            elif imported_count == 1 and len(associated_files) > 1:
                                success_msg += f" - 1 of {len(associated_files)} files accepted"
                            logger.info(success_msg)
                            successful_imports.append(folder_name)
                            any_successful_imports = True

                            # Log which specific files were imported if we can determine them
                            if len(associated_files) <= 3:  # Only log details for small numbers
                                for file in associated_files:
                                    logger.info(f"✅ Imported: '{folder_name}/{file}'")
                        else:
                            # Log rejections with file details
                            error_msg = f"❌ {folder_name}: Import failed - Readarr rejected all files"
                            if associated_files:
                                logger.error(error_msg)
                                for file in associated_files:
                                    logger.error(f"❌ Rejected: '{folder_name}/{file}'")
                            else:
                                logger.error(error_msg)
                            failed_readarr_imports.append(folder_name)

                    elif status == 'failed':
                        file_info = ""
                        if len(associated_files) == 1:
                            file_info = f" [{associated_files[0]}]"
                        elif len(associated_files) > 1:
                            file_info = f" [{len(associated_files)} files]"

                        logger.error(f"❌ {folder_name}{file_info}: Import command failed")
                        failed_readarr_imports.append(folder_name)
                        if 'message' in current_task:
                            logger.error(f"💬 Readarr error: {current_task['message']}")

                        # Log rejected files with full paths
                        if associated_files:
                            for file in associated_files:
                                logger.error(f"❌ Failed: '{folder_name}/{file}'")
                    else:
                        logger.warning(f"⚠️ {folder_name}: Unknown status - {status}")
                        failed_readarr_imports.append(folder_name)

                except Exception as e:
                    logger.error(f"❌ Error processing task result {task['id']}: {e}")
                    failed_readarr_imports.append(f"Task {task['id']}")


            # NOW handle failed imports based on whether ANY successful imports occurred
            if failed_imports:
                if any_successful_imports:
                    logger.info(f"🗑️ At least one import succeeded - deleting all {len(failed_imports)} validation failures")
                    for folder, filename, artist_name_sanitized, error_reason in failed_imports:
                        source_file_path = os.path.join(folder, filename)
                        if os.path.exists(source_file_path):
                            try:
                                os.remove(source_file_path)
                                logger.info(f"🗑️ Deleted validation failure: {filename}")
                                # Clean up empty source directory
                                if os.path.exists(folder) and not os.listdir(folder):
                                    shutil.rmtree(folder)
                                    logger.info(f"🗑️ Removed empty source directory: {folder}")
                            except Exception as e:
                                logger.error(f"❌ Error deleting validation failure {filename}: {e}")
                else:
                    logger.warning(f"📤 No successful imports - moving {len(failed_imports)} validation failures to failed_imports")
                    for folder, filename, artist_name_sanitized, error_reason in failed_imports:
                        move_failed_import_file(folder, filename, artist_name_sanitized)

            # Enhanced cleanup - only clean up truly successful imports
            truly_successful, actual_failures = cleanup_successful_imports(successful_imports)

            # Handle failed Readarr imports - DELETE if any successful imports, otherwise move to failed_imports
            if failed_readarr_imports:
                logger.warning(f"⚠️ {len(failed_readarr_imports)} folders failed Readarr import")
                for folder_name in failed_readarr_imports:
                    if os.path.exists(folder_name):
                        if any_successful_imports:
                            # Delete failed directories since we had successful imports
                            try:
                                shutil.rmtree(folder_name)
                                logger.info(f"🗑️ Deleted failed import directory: {folder_name} (successful import found)")
                            except Exception as e:
                                logger.error(f"❌ Error deleting failed directory {folder_name}: {e}")
                        else:
                            # No successful imports, move to failed_imports
                            logger.info(f"📤 Moving failed directory {folder_name} to failed_imports (no successful imports)")
                            move_failed_import_directory(folder_name)

            return failed_download

def cleanup_duplicate_directories():
    """Clean up duplicate directories and consolidate files"""
    try:
        current_dirs = next(os.walk('.'))[1]
        current_dirs = [d for d in current_dirs if d != 'failed_imports']

        # Group directories by potential author name
        author_groups = {}
        for dir_name in current_dirs:
            # Extract likely author name (first part before any separators)
            author_key = dir_name.split(' - ')[0].strip()
            if author_key not in author_groups:
                author_groups[author_key] = []
            author_groups[author_key].append(dir_name)

        # Consolidate directories for each author
        for author_key, dirs in author_groups.items():
            if len(dirs) > 1:
                logger.info(f"🔧 Consolidating {len(dirs)} directories for author: {author_key}")

                # Use the simplest directory name as the target
                target_dir = min(dirs, key=len)
                source_dirs = [d for d in dirs if d != target_dir]

                for source_dir in source_dirs:
                    try:
                        if os.path.exists(source_dir):
                            # Move all files from source to target
                            for file_name in os.listdir(source_dir):
                                source_file = os.path.join(source_dir, file_name)
                                target_file = os.path.join(target_dir, file_name)

                                if os.path.exists(target_file):
                                    # Handle duplicates
                                    if filecmp.cmp(source_file, target_file, shallow=False):
                                        os.remove(source_file)
                                        logger.info(f"🗑️ Removed duplicate file: {source_file}")
                                    else:
                                        # Rename to avoid conflict
                                        base_name, ext = os.path.splitext(file_name)
                                        counter = 1
                                        while os.path.exists(target_file):
                                            new_name = f"{base_name}_{counter}{ext}"
                                            target_file = os.path.join(target_dir, new_name)
                                            counter += 1
                                        shutil.move(source_file, target_file)
                                        logger.info(f"📤 Moved file with new name: {target_file}")
                                else:
                                    shutil.move(source_file, target_file)
                                    logger.info(f"📤 Moved file: {source_file} -> {target_file}")

                            # Remove empty source directory
                            if not os.listdir(source_dir):
                                shutil.rmtree(source_dir)
                                logger.info(f"🗑️ Removed empty directory: {source_dir}")
                    except Exception as e:
                        logger.error(f"❌ Error consolidating directory {source_dir}: {e}")
    except Exception as e:
        logger.error(f"❌ Error during directory cleanup: {e}")

def cleanup_successful_imports(successful_imports):
    """Clean up source directories after successful imports - delete rejected duplicates"""
    truly_successful = []
    failed_readarr_imports = []

    for folder_name in successful_imports:
        try:
            if os.path.exists(folder_name) and os.path.isdir(folder_name):
                files_in_dir = os.listdir(folder_name)
                book_files = [f for f in files_in_dir if f.lower().endswith(('.epub', '.pdf', '.mobi', '.azw3', '.azw'))]

                if not files_in_dir:
                    # Directory is empty - truly successful, just remove it
                    shutil.rmtree(folder_name)
                    logger.info(f"🧹 {folder_name}: Successfully imported and cleaned up (empty directory)")
                    truly_successful.append(folder_name)

                elif not book_files:
                    # No book files left, only non-essential files - truly successful
                    shutil.rmtree(folder_name)
                    logger.info(f"🧹 {folder_name}: Successfully imported and cleaned up (no book files remaining)")
                    truly_successful.append(folder_name)

                else:
                    # Still has book files - check if import actually succeeded
                    logger.warning(f"⚠️ {folder_name}: Contains {len(book_files)} book files after 'successful' import")

                    # Log the specific rejected files
                    for book_file in book_files:
                        logger.warning(f"   📄 Remaining file: {folder_name}/{book_file}")

                    # Delete individual rejected files since at least one successful import occurred
                    if len(book_files) > 1:
                        logger.info(f"🗑️ Deleting {len(book_files)} individual rejected files from {folder_name}/")
                        for book_file in book_files:
                            file_path = os.path.join(folder_name, book_file)
                            try:
                                os.remove(file_path)
                                logger.info(f"🗑️ Deleted rejected file: {folder_name}/{book_file}")
                            except Exception as e:
                                logger.error(f"❌ Error deleting file {folder_name}/{book_file}: {e}")

                        # Check if directory is now empty
                        remaining_files = os.listdir(folder_name) if os.path.exists(folder_name) else []
                        if not remaining_files:
                            shutil.rmtree(folder_name)
                            logger.info(f"🧹 {folder_name}: Cleaned up after deleting rejected files")
                            truly_successful.append(folder_name)
                        else:
                            # Still has non-book files, but that's OK for successful import
                            logger.info(f"✅ {folder_name}: Import successful (contains non-book files)")
                            truly_successful.append(folder_name)
                    else:
                        # Only one file remaining - just delete it since other imports succeeded
                        file_path = os.path.join(folder_name, book_files[0])
                        try:
                            os.remove(file_path)
                            logger.info(f"🗑️ Deleted single rejected file: {folder_name}/{book_files[0]}")

                            # Check if directory is now empty
                            remaining_files = os.listdir(folder_name) if os.path.exists(folder_name) else []
                            if not remaining_files:
                                shutil.rmtree(folder_name)
                                logger.info(f"🧹 {folder_name}: Cleaned up after deleting last rejected file")
                            truly_successful.append(folder_name)
                        except Exception as e:
                            logger.error(f"❌ Error deleting file {folder_name}/{book_files[0]}: {e}")
                            # Don't move to failed_imports, just leave it
                            truly_successful.append(folder_name)
            else:
                # Directory doesn't exist - probably already processed successfully
                logger.info(f"✅ {folder_name}: Directory not found (likely already processed)")
                truly_successful.append(folder_name)

        except Exception as e:
            logger.error(f"❌ Error processing directory {folder_name}: {e}")
            # Don't move to failed_imports on processing errors if imports succeeded elsewhere
            logger.warning(f"⚠️ Skipping cleanup for {folder_name} due to processing error")

    # Report the actual results
    if truly_successful:
        logger.info(f"✅ {len(truly_successful)} directories successfully processed")

    # NOTE: We don't report failed_readarr_imports here since we're not moving directories
    # to failed_imports in this function anymore when other imports succeeded

    return truly_successful, []  # Return empty list for failed imports

def move_failed_import_directory(folder_name):
    """Move an entire failed import directory to failed_imports"""
    try:
        failed_imports_dir = "failed_imports"
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
            logger.info(f"📁 Created failed imports directory: {failed_imports_dir}")

        # Create unique name in failed_imports
        target_path = os.path.join(failed_imports_dir, folder_name)
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
            counter += 1

        if os.path.exists(folder_name):
            shutil.move(folder_name, target_path)
            logger.info(f"📤 Moved failed import directory to: {target_path}")
        else:
            logger.warning(f"⚠️ Failed import directory not found: {folder_name}")

    except Exception as e:
        logger.error(f"❌ Error moving failed import directory {folder_name}: {e}")
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")


def move_failed_import_file(source_folder, filename, artist_name_sanitized):
    """Move a specific failed file to failed_imports directory"""
    try:
        failed_imports_dir = "failed_imports"
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
            logger.info(f"📁 Created failed imports directory: {failed_imports_dir}")

        # Create unique subdirectory for this failed import
        target_subdir = os.path.join(failed_imports_dir, artist_name_sanitized)
        counter = 1
        while os.path.exists(target_subdir):
            target_subdir = os.path.join(failed_imports_dir, f"{artist_name_sanitized}_{counter}")
            counter += 1

        os.makedirs(target_subdir, exist_ok=True)

        source_file_path = os.path.join(source_folder, filename)
        if os.path.exists(source_file_path):
            target_file_path = os.path.join(target_subdir, filename)
            shutil.move(source_file_path, target_file_path)
            logger.info(f"📤 Moved failed file to: {target_file_path}")

            # Clean up empty source directory
            if os.path.exists(source_folder) and not os.listdir(source_folder):
                shutil.rmtree(source_folder)
                logger.info(f"🗑️ Removed empty source directory: {source_folder}")
        else:
            logger.warning(f"⚠️ Failed import source file not found: {source_file_path}")

    except Exception as e:
        logger.error(f"❌ Error moving failed import {filename}: {e}")
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")


def is_docker():
    return os.getenv('IN_DOCKER') is not None

def setup_logging(config):
    if 'Logging' in config:
        log_config = config['Logging']
    else:
        log_config = DEFAULT_LOGGING_CONF

    # Setup Rich logging
    logging.basicConfig(
        level=getattr(logging, log_config.get('level', 'INFO').upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[CustomRichHandler(console=console, show_time=True, show_path=False)]
    )

def get_current_page(path: str, default_page=1) -> int:
    if os.path.exists(path):
        with open(path, 'r') as file:
            page_string = file.read().strip()
            if page_string:
                return int(page_string)
            else:
                with open(path, 'w') as file:
                    file.write(str(default_page))
                return default_page
    else:
        with open(path, 'w') as file:
            file.write(str(default_page))
        return default_page

def update_current_page(path: str, page: int) -> None:
    with open(path, 'w') as file:
        file.write(page)

def get_books(missing: bool) -> list:
    try:
        wanted = readarr.get_missing(page_size=page_size, sort_dir='ascending',sort_key='title')
    except ConnectionError as ex:
        logger.error(f"An error occurred when attempting to get records: {ex}")
        return []

    total_wanted = wanted['totalRecords']
    wanted_records = []

    if search_type == 'all':
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = readarr.get_missing(page=page, page_size=page_size, sort_dir='ascending',sort_key='title')
            except ConnectionError as ex:
                logger.error(f"Failed to grab record: {ex}")

            wanted_records.extend(wanted['records'])
            page += 1

    elif search_type == 'incrementing_page':
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = readarr.get_missing(page=page, page_size=page_size, sort_dir='ascending',sort_key='title')['records']
        except ConnectionError as ex:
            logger.error(f"Failed to grab record: {ex}")

        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, str(page))

    elif search_type == 'first_page':
        wanted_records = wanted['records']
    else:
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        raise ValueError(f'[Search Settings] - {search_type = } is not valid')

    return wanted_records

# Let's allow some overrides to be passed to the script
parser = argparse.ArgumentParser(
    description="""Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd"""
)

default_data_directory = os.getcwd()
if is_docker():
    default_data_directory = "/data"

parser.add_argument(
    "-c",
    "--config-dir",
    default=default_data_directory,
    const=default_data_directory,
    nargs="?",
    type=str,
    help="Config directory (default: %(default)s)",
)

args = parser.parse_args()

lock_file_path = os.path.join(args.config_dir, ".soularr.lock")
config_file_path = os.path.join(args.config_dir, "config.ini")
failure_file_path = os.path.join(args.config_dir, "failure_list.txt")
current_page_file_path = os.path.join(args.config_dir, ".current_page.txt")

if not is_docker() and os.path.exists(lock_file_path):
    logger.info(f"readarr_soul instance is already running.")
    sys.exit(1)

try:
    # Print startup banner
    print_startup_banner()

    if not is_docker():
        with open(lock_file_path, "w") as lock_file:
            lock_file.write("locked")

    # Disable interpolation to make storing logging formats in the config file much easier
    config = configparser.ConfigParser(interpolation=None)

    if os.path.exists(config_file_path):
        config.read(config_file_path)
    else:
        if is_docker():
            logger.error('Config file does not exist! Please mount "/data" and place your "config.ini" file there. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.')
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        else:
            logger.error("Config file does not exist! Please place it in the working directory. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.")
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")

        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        sys.exit(0)

    slskd_api_key = config['Slskd']['api_key']
    readarr_api_key = config['Readarr']['api_key']
    lidarr_download_dir = config['Readarr']['download_dir']
    lidarr_disable_sync = config.getboolean('Readarr', 'disable_sync', fallback=False)
    slskd_download_dir = config['Slskd']['download_dir']
    readarr_host_url = config['Readarr']['host_url']
    slskd_host_url = config['Slskd']['host_url']
    stalled_timeout = config.getint('Slskd', 'stalled_timeout', fallback=3600)
    delete_searches = config.getboolean('Slskd', 'delete_searches', fallback=True)
    slskd_url_base = config.get('Slskd', 'url_base', fallback='/')
    ignored_users = config.get('Search Settings', 'ignored_users', fallback='').split(",")
    search_type = config.get('Search Settings', 'search_type', fallback='first_page').lower().strip()
    search_source = config.get('Search Settings', 'search_source', fallback='missing').lower().strip()
    search_sources = [search_source]

    if search_sources[0] == 'all':
        search_sources = ['missing', 'cutoff_unmet']

    minimum_match_ratio = config.getfloat('Search Settings', 'minimum_filename_match_ratio', fallback=0.5)
    title_bonus = config.getfloat('Search Settings', 'title_bonus', fallback=0.3)
    page_size = config.getint('Search Settings', 'number_of_albums_to_grab', fallback=10)
    remove_wanted_on_failure = config.getboolean('Search Settings', 'remove_wanted_on_failure', fallback=True)
    download_filtering = config.getboolean('Download Settings', 'download_filtering', fallback=False)
    use_extension_whitelist = config.getboolean('Download Settings', 'use_extension_whitelist', fallback=False)
    extensions_whitelist = config.get('Download Settings', 'extensions_whitelist', fallback='txt,nfo,jpg').split(',')

    setup_logging(config)

    slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
    readarr = ReadarrAPI(readarr_host_url, readarr_api_key)

    # Test SLSKD connection before proceeding
    logger.info("🔍 Testing SLSKD connection...")
    if not test_slskd_connection(slskd, max_retries=2, retry_delay=60):
        logger.error("🚨 Cannot establish connection to SLSKD")
        logger.error("⚠️ Please fix the connection issue and try again")
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        sys.exit(1)

    wanted_books = []

    try:
        for source in search_sources:
            logging.debug(f'Getting records from {source}')
            missing = source == 'missing'
            wanted_books.extend(get_books(missing))
    except ValueError as ex:
        logger.error(f'An error occurred: {ex}')
        logger.error('Exiting...')
        sys.exit(0)

    download_targets = []

    if len(wanted_books) > 0:
        console.print(f"\n🎯 Found {len(wanted_books)} wanted books to process", style="bold green")

        for book in wanted_books:
            authorID = book['authorId']
            author = readarr.get_author(authorID)
            qprofile = readarr.get_quality_profile(author['qualityProfileId'])
            download_targets.append({'book':book,'author':author,'filetypes':qprofile})

        # Replace the main exception handling with more specific error handling
        if len(download_targets) > 0:
            try:
                failed = grab_most_wanted(download_targets)
            except requests.exceptions.ConnectionError as e:
                logger.error("🔌 Lost connection to SLSKD during download process")
                logger.error(f"💔 Host: {slskd_host_url}")
                logger.error("💡 SLSKD became unreachable during operation")

                # Attempt recovery
                logger.info("🔄 Attempting to recover SLSKD connection...")
                if check_slskd_recovery():
                    logger.info("✅ Connection recovered, but downloads may have been interrupted")
                    logger.info("ℹ️ Check download directory for partial downloads")
                else:
                    logger.error("❌ Could not recover connection")

                if os.path.exists(lock_file_path) and not is_docker():
                    os.remove(lock_file_path)
                sys.exit(1)
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}")
                logger.error(traceback.format_exc())
                logger.error("\n🚨 Fatal error! Exiting...")
                if os.path.exists(lock_file_path) and not is_docker():
                    os.remove(lock_file_path)
                sys.exit(1)

        print_section_header("🎉 COMPLETION SUMMARY")

        # Final cleanup with error handling
        try:
            if failed == 0:
                logger.info("Readarr_Soul finished. Exiting...")
                safe_slskd_call(slskd.transfers.remove_completed_downloads)
            else:
                if remove_wanted_on_failure:
                    logger.info(f'{failed}: releases failed and were removed from wanted list. View "failure_list.txt" for list of failed albums.')
                else:
                    logger.info(f"{failed}: releases failed while downloading and are still wanted.")
                safe_slskd_call(slskd.transfers.remove_completed_downloads)
        except Exception as e:
            logger.warning(f"⚠️ Error during final cleanup: {e}")
            logger.info("ℹ️ Script completed despite cleanup issues")

    else:
        console.print("ℹ️  No releases wanted. Nothing to do!", style="blue")
        logger.info("No releases wanted. Exiting...")

finally:
    # Remove the lock file after activity is done
    if os.path.exists(lock_file_path) and not is_docker():
        os.remove(lock_file_path)
