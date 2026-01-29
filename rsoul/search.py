import time
import logging
import copy
import os
import math
from .display import print_search_summary, print_directory_summary
from .match import book_match, verify_filetype
from .download import download_book
from .utils import get_current_page, update_current_page, is_docker

logger = logging.getLogger(__name__)


def gen_allowed_filetypes(qprofile):
    """Generate a list of allowed filetypes from a quality profile."""
    allowed_filetypes = []
    for item in qprofile["items"]:
        if item["allowed"]:
            allowed_type = item["quality"]["name"].lower()
            allowed_filetypes.append(allowed_type)
    allowed_filetypes.reverse()
    return allowed_filetypes


def is_blacklisted(ctx, title: str) -> bool:
    """Check if a title contains any blacklisted words."""
    blacklist = ctx.config.get("Search Settings", "title_blacklist", fallback="").lower().split(",")
    for word in blacklist:
        if word != "" and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False


def check_for_match(ctx, dir_cache, search_cache, target, allowed_filetype):
    """
    Check for matching files in the directory cache.

    Args:
        ctx: Application context
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
                    directory = ctx.slskd.users.directory(username=username, directory=file_dir)

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

            result = book_match(
                target,
                directory["files"],
                username,
                allowed_filetype,
                ignored_users=ctx.config.get("Search Settings", "ignored_users", fallback="").split(","),
                minimum_match_ratio=ctx.config.getfloat("Search Settings", "minimum_filename_match_ratio", fallback=0.5),
            )
            if result != None:
                return True, username, directory, file_dir, result
            else:
                continue

    return False, "", {}, "", None


def search_and_download(ctx, grab_list, target, retry_list):
    """
    Search for a book and download it if a match is found.

    Args:
        ctx: Application context
        grab_list: List of files to be grabbed
        target: Target book/author information
        retry_list: Dictionary of files to retry

    Returns:
        bool: True if a match was found and enqueued, False otherwise
    """
    book = target["book"]
    author = target["author"]
    qprofile = target["filetypes"]
    author_name = author["authorName"]
    book_title = book["title"]
    allowed_filetypes = gen_allowed_filetypes(qprofile)

    if is_blacklisted(ctx, book_title):
        return False

    delete_searches = ctx.config.getboolean("Slskd", "delete_searches", fallback=True)

    # Construct query with proper " - " separator between author and title
    query = f"{author_name} - {book_title}"
    print_search_summary(query, 0, "main", "searching")  # Show searching status

    # Perform initial search
    search = ctx.slskd.searches.search_text(
        searchText=query,
        searchTimeout=ctx.config.getint("Search Settings", "search_timeout", fallback=5000),
        filterResponses=True,
        maximumPeerQueueLength=ctx.config.getint("Search Settings", "maximum_peer_queue", fallback=50),
        minimumPeerUploadSpeed=ctx.config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
    )

    time.sleep(10)

    while True:
        state = ctx.slskd.searches.state(search["id"], False)["state"]
        if state != "InProgress":
            break
        time.sleep(1)

    search_results = ctx.slskd.searches.search_responses(search["id"])
    print_search_summary(query, len(search_results), "main", "completed")  # Show final results

    # If no results and title contains ":", try searching with main title only
    if len(search_results) == 0 and ":" in book_title:
        # Extract main title (everything before ":")
        main_title = book_title.split(":")[0].strip()
        fallback_query = f"{author_name} - {main_title}"

        logger.info(f"No results found for full title. Trying fallback search with main title: {fallback_query}")

        # Delete the original search to clean up
        if delete_searches:
            ctx.slskd.searches.delete(search["id"])

        print_search_summary(fallback_query, 0, "fallback", "searching")  # Show searching status

        # Perform fallback search
        search = ctx.slskd.searches.search_text(
            searchText=fallback_query,
            searchTimeout=ctx.config.getint("Search Settings", "search_timeout", fallback=5000),
            filterResponses=True,
            maximumPeerQueueLength=ctx.config.getint("Search Settings", "maximum_peer_queue", fallback=50),
            minimumPeerUploadSpeed=ctx.config.getint("Search Settings", "minimum_peer_upload_speed", fallback=0),
        )

        time.sleep(10)

        while True:
            state = ctx.slskd.searches.state(search["id"], False)["state"]
            if state != "InProgress":
                break
            time.sleep(1)

        search_results = ctx.slskd.searches.search_responses(search["id"])
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
        found, username, directory, file_dir, file = check_for_match(ctx, dir_cache, search_cache, target, allowed_filetype)

        if found:
            if download_book(ctx.slskd, target, username, file_dir, directory, retry_list, grab_list, file):
                if delete_searches:
                    ctx.slskd.searches.delete(search["id"])
                return True

    if delete_searches:
        ctx.slskd.searches.delete(search["id"])
    return False


def get_books(ctx, search_source, search_type, page_size) -> list:
    """Get books from Readarr based on search source and type."""
    current_page_file_path = os.path.join(ctx.config_dir, ".current_page.txt")

    api_method = ctx.readarr.get_missing if search_source == "missing" else ctx.readarr.get_cutoff

    try:
        wanted = api_method(page_size=page_size, sort_dir="ascending", sort_key="title")
    except Exception as ex:
        logger.error(f"An error occurred when attempting to get records from {search_source}: {ex}")
        return []

    total_wanted = wanted["totalRecords"]
    wanted_records = []

    if search_type == "all":
        page = 1
        while len(wanted_records) < total_wanted:
            try:
                wanted = api_method(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")
                wanted_records.extend(wanted["records"])
            except Exception as ex:
                logger.error(f"Failed to grab records from {search_source} page {page}: {ex}")
                break
            page += 1

    elif search_type == "incrementing_page":
        page = get_current_page(current_page_file_path)
        try:
            wanted_records = api_method(page=page, page_size=page_size, sort_dir="ascending", sort_key="title")["records"]
        except Exception as ex:
            logger.error(f"Failed to grab record from {search_source}: {ex}")

        page = 1 if page >= math.ceil(total_wanted / page_size) else page + 1
        update_current_page(current_page_file_path, page)

    elif search_type == "first_page":
        wanted_records = wanted["records"]
    else:
        raise ValueError(f"[Search Settings] - {search_type = } is not valid")

    return wanted_records
