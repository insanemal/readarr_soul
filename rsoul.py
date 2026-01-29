#!/usr/bin/env python

import sys

sys.path.append(sys.path[0] + "./pyarr/")
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


# Safe terminal width detection with proper error handling
def get_terminal_width():
    """Get terminal width with fallback for environments without a terminal"""
    try:
        # Try to get actual terminal size
        if hasattr(os, "get_terminal_size"):
            return os.get_terminal_size().columns
        else:
            return 120  # Fallback for older Python versions
    except (OSError, ValueError):
        # Handle cases where there's no terminal (Docker, CI/CD, etc.)
        # Try environment variables first
        try:
            width = os.environ.get("COLUMNS")
            if width:
                return int(width)
        except (ValueError, TypeError):
            pass

        # Final fallback
        return 120


# Initialize rich console with safe width detection
terminal_width = get_terminal_width()
console = Console(width=terminal_width, force_terminal=True)


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


logger = logging.getLogger("readarr_soul")

# Enhanced logging configuration with Rich
DEFAULT_LOGGING_CONF = {
    "level": "INFO",
    "format": "[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
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
    console.print(Panel(Text(banner_text, style="bold cyan"), box=box.DOUBLE, expand=True, width=console.width))


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
        file_count = dir_info.get("fileCount", 0)
        dir_name = dir_info.get("name", "Unknown")
    elif isinstance(directory_data, dict):
        file_count = len(directory_data.get("files", []))
        dir_name = directory_data.get("name", "Unknown")
    else:
        file_count = 0
        dir_name = "Unknown"

    # Force full width
    table = Table(show_header=False, box=box.SIMPLE, expand=True, width=console.width)
    table.add_column("", style="cyan", ratio=1, min_width=20)
    table.add_column("", style="white", ratio=4)

    table.add_row("👤 User:", username)
    table.add_row("📁 Directory:", dir_name.split("\\")[-1])
    table.add_row("📄 Files:", f"{file_count} files")

    console.print(table)


def print_download_summary(downloads):
    """Print a formatted table of downloads using full width"""
    if not downloads:
        console.print("❌ No downloads to process", style="red")
        return

    # Force full width with explicit width setting
    table = Table(title="📥 Download Queue", box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("👤 Username", style="cyan", ratio=1, min_width=15)
    table.add_column("📁 Directory", style="magenta", ratio=3)

    for download in downloads:
        username = download["username"]
        for dir_info in download["directories"]:
            table.add_row(username, dir_info["directory"])

    console.print(table)


def print_import_summary(commands):
    """Print a formatted table of import operations using full width"""
    if not commands:
        return

    # Force full width
    table = Table(title="📚 Import Operations", box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("👤 Author", style="green", ratio=2, min_width=20)
    table.add_column("🆔 Command ID", style="yellow", ratio=1, min_width=12)
    table.add_column("📊 Status", style="white", ratio=1, min_width=10)

    for command in commands:
        # Extract author name from command if available
        author_name = "Unknown"
        if "body" in command and "path" in command["body"]:
            path = command["body"]["path"]
            author_name = os.path.basename(path)

        table.add_row(author_name, str(command["id"]), "Queued")

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


def book_match(target, slskd_files, username, filetype):
    """
    Match target book with available files, filtering by correct filetype.
    Enhanced to handle variations in punctuation, underscores, and additional text.

    Args:
        target: Target book information
        slskd_files: List of available files
        username: Username of the file owner
        filetype: Required file type (e.g., 'epub', 'pdf')

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
        import re

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
            ratio = check_ratio(" ", ratio, pattern, slskd_filename)
            max_ratio = max(max_ratio, ratio)

            ratio = check_ratio("_", ratio, pattern, slskd_filename)
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


def check_ratio(separator, ratio, book_filename, slskd_filename):
    if ratio < minimum_match_ratio:
        if separator != "":
            book_filename_word_count = len(book_filename.split()) * -1
            truncated_slskd_filename = " ".join(slskd_filename.split(separator)[book_filename_word_count:])
            ratio = difflib.SequenceMatcher(None, book_filename, truncated_slskd_filename).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, book_filename, slskd_filename).ratio()
        return ratio
    return ratio


def sanitize_folder_name(folder_name):
    valid_characters = re.sub(r'[<>:."/\\|?*]', "", folder_name)
    return valid_characters.strip()


def cancel_and_delete(delete_dir, username, files):
    for file in files:
        slskd.transfers.cancel_download(username=username, id=file["id"])

    os.chdir(slskd_download_dir)
    if os.path.exists(delete_dir):
        shutil.rmtree(delete_dir)


def choose_edition(author_name, editions):
    # This might need to be adjusted based on actual Readarr edition data structure
    # For now, just return the first edition as a placeholder or implement basic filtering if needed
    for edition in editions:
        # Placeholder logic: accept all or filter by specific criteria
        # language = edition.get('language', 'Unknown')
        # if language == 'English': ...
        logger.info(f"Selected edition for {author_name}: {edition.get('title', 'Unknown')} (ID: {edition.get('id', 'Unknown')})")
        return edition

    if editions:
        return editions[0]
    return None


def verify_filetype(file, allowed_filetype):
    current_filetype = file["filename"].split(".")[-1].lower()
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
                        if len(directory) > 0 and isinstance(directory[0], dict) and "files" in directory[0]:
                            logger.info("Converting list to dictionary format - extracting files from directory object")
                            # Preserve the original directory name for later matching
                            directory = {"files": directory[0]["files"], "name": directory[0]["name"]}
                        else:
                            logger.warning(f"Unexpected list structure from user: {username}, folder: {file_dir}")
                            continue
                    elif not isinstance(directory, dict) or "files" not in directory:
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

            result = book_match(target, directory["files"], username, allowed_filetype)
            if result != None:
                return True, username, directory, file_dir, result
            else:
                continue

    return False, "", {}, "", None


def gen_allowed_filetypes(qprofile):
    allowed_filetypes = []
    for item in qprofile["items"]:
        if item["allowed"]:
            allowed_type = item["quality"]["name"].lower()
            allowed_filetypes.append(allowed_type)
    allowed_filetypes.reverse()
    return allowed_filetypes


def search_and_download(grab_list, target, retry_list):
    book = target["book"]
    author = target["author"]
    qprofile = target["filetypes"]
    artist_name = author["authorName"]
    artist_id = author["id"]
    album_id = book["id"]
    album_title = book["title"]
    allowed_filetypes = gen_allowed_filetypes(qprofile)

    if is_blacklisted(album_title):
        return False

    # Construct query with proper " - " separator between author and title
    query = f"{artist_name} - {album_title}"
    print_search_summary(query, 0, "main", "searching")  # Show searching status

    # Perform initial search
    search = slskd.searches.search_text(
        searchText=query,
        searchTimeout=config.getint("Search Settings", "search_timeout", fallback=5000),
        filterResponses=True,
        maximumPeerQueueLength=config.getint("Search Settings", "maximum_peer_queue", fallback=50),
        minimumPeerUploadSpeed=config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
    )

    time.sleep(10)

    while True:
        state = slskd.searches.state(search["id"], False)["state"]
        if state != "InProgress":
            break
        time.sleep(1)

    search_results = slskd.searches.search_responses(search["id"])
    print_search_summary(query, len(search_results), "main", "completed")  # Show final results

    # If no results and title contains ":", try searching with main title only
    if len(search_results) == 0 and ":" in album_title:
        # Extract main title (everything before ":")
        main_title = album_title.split(":")[0].strip()
        fallback_query = f"{artist_name} - {main_title}"

        logger.info(f"No results found for full title. Trying fallback search with main title: {fallback_query}")

        # Delete the original search to clean up
        if delete_searches:
            slskd.searches.delete(search["id"])

        print_search_summary(fallback_query, 0, "fallback", "searching")  # Show searching status

        # Perform fallback search
        search = slskd.searches.search_text(
            searchText=fallback_query,
            searchTimeout=config.getint("Search Settings", "search_timeout", fallback=5000),
            filterResponses=True,
            maximumPeerQueueLength=config.getint("Search Settings", "maximum_peer_queue", fallback=50),
            minimumPeerUploadSpeed=config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
        )

        time.sleep(10)

        while True:
            state = slskd.searches.state(search["id"], False)["state"]
            if state != "InProgress":
                break
            time.sleep(1)

        search_results = slskd.searches.search_responses(search["id"])
        print_search_summary(fallback_query, len(search_results), "fallback", "completed")  # Show final results

    # Continue with existing logic using search_results
    dir_cache = {}
    search_cache = {}

    for result in search_results:
        username = result["username"]
        if username not in dir_cache:
            dir_cache[username] = {}

        logger.info(f"Truncating directory count of user: {username}")
        init_files = result["files"]

        for file in init_files:
            file_dir = file["filename"].rsplit("\\", 1)[0]
            for allowed_filetype in allowed_filetypes:
                if verify_filetype(file, allowed_filetype):
                    if allowed_filetype not in dir_cache[username]:
                        dir_cache[username][allowed_filetype] = []
                    if file_dir not in dir_cache[username][allowed_filetype]:
                        dir_cache[username][allowed_filetype].append(file_dir)

    for allowed_filetype in allowed_filetypes:
        logger.info(f"Searching for matches with selected attributes: {allowed_filetype}")
        found, username, directory, file_dir, file = check_for_match(dir_cache, search_cache, target, allowed_filetype)

        if found:
            if download_book(target, username, file_dir, directory, retry_list, grab_list, file):
                if delete_searches:
                    slskd.searches.delete(search["id"])
                return True

    if delete_searches:
        slskd.searches.delete(search["id"])
    return False


def slskd_do_enqueue(username, files, file_dir):
    """
    Takes a list of files to download and returns a list of files that were successfully added to the download queue
    It also adds to each file the details needed to track that specific file.
    """
    downloads = []
    try:
        enqueue = slskd.transfers.enqueue(username=username, files=files)
    except Exception:
        logger.debug("Enqueue failed", exc_info=True)
        return None

    if enqueue:
        time.sleep(5)
        # Fetch downloads to get IDs
        try:
            download_list = slskd.transfers.get_downloads(username=username)
            for file in files:
                for directory in download_list["directories"]:
                    # Match directory name (ignoring path differences if possible, but soularr uses exact match)
                    # rsoul uses sanitized names or just passes directory['name']
                    # We need to be careful here. In rsoul, file_dir is the full path?
                    # Let's check how file_dir is passed.
                    if directory["directory"] == file_dir.split("\\")[-1] or directory["directory"] == file_dir:
                        for slskd_file in directory["files"]:
                            if file["filename"].split("\\")[-1] == slskd_file["filename"]:
                                file_details = {}
                                file_details["filename"] = file["filename"]
                                file_details["id"] = slskd_file["id"]
                                file_details["file_dir"] = file_dir
                                file_details["username"] = username
                                file_details["size"] = file["size"]
                                downloads.append(file_details)
            return downloads
        except Exception as e:
            logger.error(f"Error getting download list after enqueue: {e}")
            return None
    else:
        return None


def slskd_download_status(downloads):
    """
    Takes a list of files and gets the status of each file and packs it into the file object.
    """
    ok = True
    for file in downloads:
        try:
            status = slskd.transfers.get_download(file["username"], file["id"])
            file["status"] = status
        except Exception:
            logger.exception(f"Error getting download status of {file['filename']}")
            file["status"] = None
            ok = False
    return ok


def downloads_all_done(downloads):
    """
    Checks the status of all the files in an album and returns a flag if all done as well
    as returning a list of files with errors to check and how many files are in "Queued, Remotely"
    """
    all_done = True
    error_list = []
    remote_queue = 0
    for file in downloads:
        if file["status"] is not None:
            if not file["status"]["state"] == "Completed, Succeeded":
                all_done = False
            if file["status"]["state"] in [
                "Completed, Cancelled",
                "Completed, TimedOut",
                "Completed, Errored",
                "Completed, Rejected",
                "Completed, Aborted",
            ]:
                error_list.append(file)
            if file["status"]["state"] == "Queued, Remotely":
                remote_queue += 1
    if not len(error_list) > 0:
        error_list = None
    return all_done, error_list, remote_queue


def download_book(target, username, file_dir, directory, retry_list, grab_list, file):
    directory["files"] = [file]
    filename = file["filename"]

    for i in range(0, len(directory["files"])):
        directory["files"][i]["filename"] = file_dir + "\\" + directory["files"][i]["filename"]

    # Use the new enqueue function that returns tracked file objects with IDs
    downloads = slskd_do_enqueue(username, directory["files"], file_dir)

    if downloads:
        folder_data = {
            "author_name": target["author"]["authorName"],
            "title": target["book"]["title"],
            "bookId": target["book"]["id"],
            "dir": file_dir.split("\\")[-1],
            "username": username,
            "directory": directory,
            "filename": filename,
            "files": downloads,  # Store the tracked files list
            "count_start": time.time(),  # Initialize start time for timeouts
            "rejected_retries": 0,
            "error_count": 0,
        }

        grab_list.append(folder_data)
        return True
    else:
        logger.warning(f"Failed to enqueue download for {target['book']['title']} from {username}")
        # Add to ignored users?
        ignored_users.append(username)
        return False


def is_blacklisted(title: str) -> bool:
    blacklist = config.get("Search Settings", "title_blacklist", fallback="").lower().split(",")
    for word in blacklist:
        if word != "" and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False


def grab_most_wanted(download_targets):
    grab_list = []
    failed_download = 0
    success = False
    retry_list = {}

    print_section_header("🎯 STARTING SEARCH PHASE")

    for target in download_targets:
        book = target["book"]
        author = target["author"]
        artist_name = author["authorName"]

        success = search_and_download(grab_list, target, retry_list)

        if not success:
            if remove_wanted_on_failure:
                logger.error(f"Failed to grab album: {book['title']} for artist: {artist_name}." + ' Failed album removed from wanted list and added to "failure_list.txt"')
                book["monitored"] = False
                edition = readarr.get_edition(book["id"])
                readarr.upd_book(book=book, editions=edition)

                current_datetime = datetime.now()
                current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")
                failure_string = current_datetime_str + " - " + artist_name + ", " + book["title"] + "\n"

                with open(failure_file_path, "a") as file:
                    file.write(failure_string)
            else:
                logger.error(f"Failed to grab album: {book['title']} for artist: {artist_name}")

            failed_download += 1

    print_section_header("📥 DOWNLOAD MONITORING PHASE")

    downloads = slskd.transfers.get_all_downloads()
    print_download_summary(downloads)

    logger.info(f"Waiting for downloads... monitor at: {''.join([slskd_host_url, slskd_url_base, 'downloads'])}")

    while True:
        if not grab_list:
            break

        unfinished = 0

        # Iterate over a copy of the list so we can modify the original
        for artist_folder in list(grab_list):
            username = artist_folder["username"]

            # Update status for all files in this folder using ID-based tracking
            if not slskd_download_status(artist_folder["files"]):
                artist_folder["error_count"] += 1
                # If we can't get status consistently, we might need to assume failure eventually
                # For now, just continue and hope next loop works

            # Check overall status
            album_done, problems, remote_queued_count = downloads_all_done(artist_folder["files"])

            # Check Stalled Timeout (Total time since start)
            if (time.time() - artist_folder["count_start"]) >= stalled_timeout:
                logger.error(f"Timeout waiting for download: {artist_folder['title']} from {username}")
                cancel_and_delete(artist_folder["dir"], username, artist_folder["files"])
                grab_list.remove(artist_folder)
                failed_download += 1
                continue

            # Check Remote Queue Timeout (Time stuck in remote queue)
            if remote_queued_count == len(artist_folder["files"]):
                if (time.time() - artist_folder["count_start"]) >= remote_queue_timeout:
                    logger.error(f"Remote queue timeout: {artist_folder['title']} from {username}")
                    cancel_and_delete(artist_folder["dir"], username, artist_folder["files"])
                    grab_list.remove(artist_folder)
                    failed_download += 1
                    continue

            if not album_done:
                unfinished += 1

            # Handle Problems
            if problems:
                abort_album = False

                # Check if we should abort based on types of errors
                for prob_file in problems:
                    state = prob_file["status"]["state"]

                    # RETRY LOGIC
                    if state in ["Completed, Cancelled", "Completed, TimedOut", "Completed, Errored", "Completed, Aborted", "Completed, Rejected"]:
                        # Special handling for "Completed, Rejected"
                        if state == "Completed, Rejected":
                            if len(problems) == len(artist_folder["files"]):
                                logger.error(f"All files rejected by user {username}")
                                abort_album = True
                                break

                            # Check if we have retried too many times for rejections
                            if artist_folder["rejected_retries"] >= int(len(artist_folder["files"]) * 1.2):
                                logger.error(f"Too many rejection retries for {username}")
                                abort_album = True
                                break

                            artist_folder["rejected_retries"] += 1

                        # Locate the specific file in our main list to update its retry count
                        for track_file in artist_folder["files"]:
                            if track_file["filename"] == prob_file["filename"]:
                                if "retry" not in track_file:
                                    track_file["retry"] = 0

                                track_file["retry"] += 1

                                if track_file["retry"] < 5:
                                    logger.info(f"Retrying file: {track_file['filename']} (Attempt {track_file['retry']})")
                                    # Re-queue specific file
                                    requeue = slskd_do_enqueue(username, [track_file], artist_folder["dir"])

                                    if requeue:
                                        # Update ID
                                        track_file["id"] = requeue[0]["id"]
                                        # Reset status to None so we don't catch it again immediately
                                        track_file["status"] = None
                                        time.sleep(1)
                                    else:
                                        logger.warning(f"Failed to requeue {track_file['filename']}")
                                        abort_album = True
                                else:
                                    logger.error(f"Max retries reached for {track_file['filename']}")
                                    abort_album = True
                                break

                    if abort_album:
                        break

                if abort_album:
                    logger.error(f"Aborting download for {artist_folder['title']} from {username}")
                    cancel_and_delete(artist_folder["dir"], username, artist_folder["files"])
                    grab_list.remove(artist_folder)
                    failed_download += 1
                    continue

        if unfinished == 0:
            logger.info("All downloads finished!")
            time.sleep(5)
            break

        time.sleep(10)

    print_section_header("📚 METADATA VALIDATION & IMPORT PHASE")

    # Check if sync is disabled first
    if readarr_disable_sync:
        logger.warning("⚠️ Readarr sync is disabled in config. Skipping import phase.")
        logger.info(f"Files downloaded but not imported. Check download directory: {slskd_download_dir}")
        return failed_download

    os.chdir(slskd_download_dir)
    logger.info(f"📁 Changed to download directory: {slskd_download_dir}")

    commands = []
    grab_list.sort(key=operator.itemgetter("author_name"))
    failed_imports = []

    for artist_folder in grab_list:
        try:
            author_name = artist_folder["author_name"]
            author_name_sanitized = sanitize_folder_name(author_name)
            folder = artist_folder["dir"]
            filename = artist_folder["filename"]
            book_title = artist_folder["title"]
            book_id = artist_folder["bookId"]

            logger.info(f"🔍 Processing file: {filename} for book: {book_title}")
            logger.info(f"📂 Source folder: {folder}")
            logger.info(f"👤 Target author folder: {author_name_sanitized}")

            # Check if source file exists
            source_file_path = os.path.join(folder, filename)
            if not os.path.exists(source_file_path):
                logger.error(f"❌ Source file not found: {source_file_path}")
                failed_imports.append((folder, filename, author_name_sanitized, f"Source file not found: {source_file_path}"))
                continue

            logger.info(f"✅ Source file exists: {source_file_path}")

            extension = filename.split(".")[-1].lower()
            match = False

            # Enhanced metadata validation with better error handling
            if extension in ["azw3", "mobi"]:
                try:
                    logger.info(f"📖 Reading MOBI/AZW3 metadata from: {source_file_path}")
                    metadata = MobiHeader(source_file_path)
                    isbn = metadata.get_exth_value_by_id(104)

                    if isbn is not None:
                        logger.info(f"📚 Found ISBN in metadata: {isbn}")
                        try:
                            book_lookup = readarr.lookup(term=f"isbn:{str(isbn).strip()}")
                            if book_lookup and len(book_lookup) > 0:
                                book_to_test = book_lookup[0]["id"]
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

            elif extension == "epub":
                try:
                    logger.info(f"📖 Reading EPUB metadata from: {source_file_path}")
                    metadata = ebookmeta.get_metadata(source_file_path)
                    title = metadata.title

                    if title:
                        logger.info(f"📚 Found title in metadata: '{title}'")
                        logger.info(f"🎯 Expected title: '{book_title}'")

                        # Enhanced title matching
                        diff = difflib.SequenceMatcher(None, title, book_title).ratio()
                        logger.info(f"📊 Exact title match ratio: {diff:.3f}")

                        normalized_title = re.sub(r"[^\w\s]", "", title.lower())
                        normalized_book_title = re.sub(r"[^\w\s]", "", book_title.lower())
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

                # Create target directory
                if not os.path.exists(author_name_sanitized):
                    logger.info(f"📁 Creating author directory: {author_name_sanitized}")
                    try:
                        os.makedirs(author_name_sanitized, exist_ok=True)
                    except Exception as e:
                        logger.error(f"❌ Failed to create directory {author_name_sanitized}: {e}")
                        failed_imports.append((folder, filename, author_name_sanitized, f"Failed to create directory: {e}"))
                        continue

                # Move file to target directory
                target_file_path = os.path.join(author_name_sanitized, filename)

                if os.path.exists(source_file_path) and not os.path.exists(target_file_path):
                    try:
                        logger.info(f"📤 Moving file from {source_file_path} to {target_file_path}")
                        shutil.move(source_file_path, target_file_path)
                        logger.info("✅ File moved successfully")

                        # Clean up source directory if empty
                        try:
                            if os.path.exists(folder) and not os.listdir(folder):
                                logger.info(f"🗑️ Removing empty source directory: {folder}")
                                shutil.rmtree(folder)
                        except Exception as e:
                            logger.warning(f"⚠️ Could not remove source directory {folder}: {e}")

                    except Exception as e:
                        logger.error(f"❌ Failed to move file: {e}")
                        failed_imports.append((folder, filename, author_name_sanitized, f"Failed to move file: {e}"))
                        continue
                else:
                    if not os.path.exists(source_file_path):
                        logger.warning(f"⚠️ Source file no longer exists: {source_file_path}")
                    if os.path.exists(target_file_path):
                        logger.warning(f"⚠️ Target file already exists: {target_file_path}")

            else:
                logger.warning(f"❌ Metadata validation failed for {filename}")
                failed_imports.append((folder, filename, author_name_sanitized, "Metadata validation failed"))

        except Exception as e:
            logger.error(f"❌ Unexpected error processing {artist_folder.get('filename', 'unknown')}: {e}")
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            failed_imports.append((artist_folder.get("dir", "unknown"), artist_folder.get("filename", "unknown"), artist_folder.get("author_name", "unknown"), f"Unexpected error: {e}"))

    # Handle failed imports
    if failed_imports:
        logger.warning(f"⚠️ {len(failed_imports)} files failed validation/processing")

        for folder, filename, author_name_sanitized, error_reason in failed_imports:
            logger.warning(f"❌ Failed: {filename} - Reason: {error_reason}")

            failed_imports_dir = "failed_imports"
            try:
                if not os.path.exists(failed_imports_dir):
                    os.makedirs(failed_imports_dir)
                    logger.info(f"📁 Created failed imports directory: {failed_imports_dir}")

                target_path = os.path.join(failed_imports_dir, author_name_sanitized)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(failed_imports_dir, f"{author_name_sanitized}_{counter}")
                    counter += 1

                os.makedirs(target_path, exist_ok=True)

                source_file_path = os.path.join(folder, filename)
                if os.path.exists(source_file_path):
                    shutil.move(source_file_path, target_path)
                    logger.info(f"📤 Moved failed file to: {target_path}")

                    if os.path.exists(folder) and not os.listdir(folder):
                        shutil.rmtree(folder)

            except Exception as e:
                logger.error(f"❌ Error handling failed import for {filename}: {e}")

    # Get list of successfully processed author folders
    try:
        artist_folders = next(os.walk("."))[1]
        artist_folders = [folder for folder in artist_folders if folder != "failed_imports"]
        logger.info(f"📂 Found {len(artist_folders)} author folders to import: {artist_folders}")
    except Exception as e:
        logger.error(f"❌ Error listing directories: {e}")
        artist_folders = []

    # Start Readarr import process
    if artist_folders:
        logger.info("🚀 Starting Readarr import commands...")

        for artist_folder in artist_folders:
            try:
                download_dir = os.path.join(readarr_download_dir, artist_folder)
                logger.info(f"📚 Importing from: {download_dir}")

                command = readarr.post_command(name="DownloadedBooksScan", path=download_dir)
                commands.append(command)
                logger.info(f"✅ Import command created - ID: {command['id']} for folder: {artist_folder}")

            except Exception as e:
                logger.error(f"❌ Failed to create import command for {artist_folder}: {e}")
                logger.error(f"🔍 Traceback: {traceback.format_exc()}")

        if commands:
            print_import_summary(commands)

            # Monitor import progress
            logger.info("⏳ Monitoring import progress...")
            while True:
                completed_count = 0

                for task in commands:
                    try:
                        current_task = readarr.get_command(task["id"])
                        if current_task["status"] in ["completed", "failed"]:
                            completed_count += 1
                    except Exception as e:
                        logger.error(f"❌ Error checking task {task['id']}: {e}")
                        completed_count += 1  # Count as completed to avoid infinite loop

                if completed_count == len(commands):
                    break

                time.sleep(2)

            # Report final results
            logger.info("📊 Import Results:")
            for task in commands:
                try:
                    current_task = readarr.get_command(task["id"])
                    status = current_task.get("status", "unknown")

                    if "body" in current_task and "path" in current_task["body"]:
                        path = current_task["body"]["path"]
                        folder_name = os.path.basename(path)
                    else:
                        folder_name = f"Task {task['id']}"

                    if status == "completed":
                        logger.info(f"✅ {folder_name}: Import completed successfully")
                    elif status == "failed":
                        logger.error(f"❌ {folder_name}: Import failed")
                        if "message" in current_task:
                            logger.error(f"💬 Error message: {current_task['message']}")

                        # Move failed import
                        if "body" in current_task and "path" in current_task["body"]:
                            move_failed_import(current_task["body"]["path"])
                    else:
                        logger.warning(f"⚠️ {folder_name}: Import status unknown - {status}")

                except Exception as e:
                    logger.error(f"❌ Error processing task result {task['id']}: {e}")
                    logger.error(f"🔍 Raw task data: {task}")
        else:
            logger.warning("⚠️ No import commands were created successfully")
    else:
        logger.warning("⚠️ No author folders found to import")

    return failed_download


def move_failed_import(src_path):
    """Move failed import to failed_imports directory with better error handling"""
    try:
        failed_imports_dir = "failed_imports"
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
            logger.info(f"📁 Created failed imports directory: {failed_imports_dir}")

        folder_name = os.path.basename(src_path)
        target_path = os.path.join(failed_imports_dir, folder_name)
        counter = 1

        while os.path.exists(target_path):
            target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
            counter += 1

        if os.path.exists(folder_name):
            shutil.move(folder_name, target_path)
            logger.info(f"📤 Failed import moved to: {target_path}")
        else:
            logger.warning(f"⚠️ Failed import source not found: {folder_name}")

    except Exception as e:
        logger.error(f"❌ Error moving failed import from {src_path}: {e}")
        logger.error(f"🔍 Traceback: {traceback.format_exc()}")


def is_docker():
    return os.getenv("IN_DOCKER") is not None


def setup_logging(config):
    if "Logging" in config:
        log_config = config["Logging"]
    else:
        log_config = DEFAULT_LOGGING_CONF

    # Setup Rich logging
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO").upper()), format="%(message)s", datefmt="[%X]", handlers=[CustomRichHandler(console=console, show_time=True, show_path=False)]
    )


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


def get_books(missing: bool) -> list:
    try:
        wanted = readarr.get_missing(page_size=page_size, sort_dir="ascending", sort_key="title")
    except ConnectionError as ex:
        logger.error(f"An error occurred when attempting to get records: {ex}")
        return []

    total_wanted = wanted["totalRecords"]
    wanted_records = []

    if search_type == "all":
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = readarr.get_missing(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")
            except ConnectionError as ex:
                logger.error(f"Failed to grab record: {ex}")

            wanted_records.extend(wanted["records"])
            page += 1

    elif search_type == "incrementing_page":
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = readarr.get_missing(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")["records"]
        except ConnectionError as ex:
            logger.error(f"Failed to grab record: {ex}")

        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, page)

    elif search_type == "first_page":
        wanted_records = wanted["records"]
    else:
        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        raise ValueError(f"[Search Settings] - {search_type = } is not valid")

    return wanted_records


# Let's allow some overrides to be passed to the script
parser = argparse.ArgumentParser(description="""Soularr reads all of your "wanted" albums/artists from Lidarr and downloads them using Slskd""")

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
            logger.error(
                'Config file does not exist! Please mount "/data" and place your "config.ini" file there. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else.'
            )
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")
        else:
            logger.error(
                "Config file does not exist! Please place it in the working directory. Alternatively, pass `--config-dir /directory/of/your/liking` as post arguments to store the config somewhere else."
            )
            logger.error("See: https://github.com/mrusse/soularr/blob/main/config.ini for an example config file.")

        if os.path.exists(lock_file_path) and not is_docker():
            os.remove(lock_file_path)
        sys.exit(0)

    slskd_api_key = config["Slskd"]["api_key"]
    readarr_api_key = config["Readarr"]["api_key"]
    readarr_download_dir = config["Readarr"]["download_dir"]
    readarr_disable_sync = config.getboolean("Readarr", "disable_sync", fallback=False)
    slskd_download_dir = config["Slskd"]["download_dir"]
    readarr_host_url = config["Readarr"]["host_url"]
    slskd_host_url = config["Slskd"]["host_url"]
    stalled_timeout = config.getint("Slskd", "stalled_timeout", fallback=3600)
    remote_queue_timeout = config.getint("Slskd", "remote_queue_timeout", fallback=300)
    delete_searches = config.getboolean("Slskd", "delete_searches", fallback=True)
    slskd_url_base = config.get("Slskd", "url_base", fallback="/")
    ignored_users = config.get("Search Settings", "ignored_users", fallback="").split(",")
    search_type = config.get("Search Settings", "search_type", fallback="first_page").lower().strip()
    search_source = config.get("Search Settings", "search_source", fallback="missing").lower().strip()
    search_sources = [search_source]

    if search_sources[0] == "all":
        search_sources = ["missing", "cutoff_unmet"]

    minimum_match_ratio = config.getfloat("Search Settings", "minimum_filename_match_ratio", fallback=0.5)
    page_size = config.getint("Search Settings", "number_of_books_to_grab", fallback=config.getint("Search Settings", "number_of_albums_to_grab", fallback=10))
    remove_wanted_on_failure = config.getboolean("Search Settings", "remove_wanted_on_failure", fallback=True)
    download_filtering = config.getboolean("Download Settings", "download_filtering", fallback=False)
    use_extension_whitelist = config.getboolean("Download Settings", "use_extension_whitelist", fallback=False)
    extensions_whitelist = config.get("Download Settings", "extensions_whitelist", fallback="txt,nfo,jpg").split(",")

    setup_logging(config)

    slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
    readarr = ReadarrAPI(readarr_host_url, readarr_api_key)

    wanted_books = []

    try:
        for source in search_sources:
            logging.debug(f"Getting records from {source}")
            missing = source == "missing"
            wanted_books.extend(get_books(missing))
    except ValueError as ex:
        logger.error(f"An error occurred: {ex}")
        logger.error("Exiting...")
        sys.exit(0)

    download_targets = []

    if len(wanted_books) > 0:
        console.print(f"\n🎯 Found {len(wanted_books)} wanted books to process", style="bold green")

        for book in wanted_books:
            authorID = book["authorId"]
            author = readarr.get_author(authorID)
            qprofile = readarr.get_quality_profile(author["qualityProfileId"])
            download_targets.append({"book": book, "author": author, "filetypes": qprofile})

    if len(download_targets) > 0:
        try:
            failed = grab_most_wanted(download_targets)
        except Exception:
            logger.error(traceback.format_exc())
            logger.error("\n Fatal error! Exiting...")
            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)
            sys.exit(0)

        print_section_header("🎉 COMPLETION SUMMARY")

        if failed == 0:
            console.print("✅ All downloads completed successfully!", style="bold green")
            logger.info("Readarr_Soul finished. Exiting...")
            slskd.transfers.remove_completed_downloads()
        else:
            if remove_wanted_on_failure:
                console.print(f"⚠️  {failed} releases failed and were removed from wanted list. Check 'failure_list.txt' for details.", style="yellow")
                logger.info(f'{failed}: releases failed and were removed from wanted list. View "failure_list.txt" for list of failed albums.')
            else:
                console.print(f"❌ {failed} releases failed but are still wanted.", style="red")
                logger.info(f"{failed}: releases failed while downloading and are still wanted.")
            slskd.transfers.remove_completed_downloads()
    else:
        console.print("ℹ️  No releases wanted. Nothing to do!", style="blue")
        logger.info("No releases wanted. Exiting...")

finally:
    # Remove the lock file after activity is done
    if os.path.exists(lock_file_path) and not is_docker():
        os.remove(lock_file_path)
