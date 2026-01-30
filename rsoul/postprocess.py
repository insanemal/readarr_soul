import os
import shutil
import logging
import re
import difflib
import time
import operator
from typing import Any

from mobi_header import MobiHeader
import ebookmeta
from .utils import sanitize_folder_name
from .display import print_import_summary, print_section_header

logger = logging.getLogger("readarr_soul")


def move_failed_import(src_path: str):
    """Move failed import to failed_imports directory with better error handling"""
    try:
        failed_imports_dir = "failed_imports"
        if not os.path.exists(failed_imports_dir):
            os.makedirs(failed_imports_dir)
            logger.info(f"Created failed imports directory: {failed_imports_dir}")

        folder_name = os.path.basename(src_path)
        target_path = os.path.join(failed_imports_dir, folder_name)
        counter = 1

        while os.path.exists(target_path):
            target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
            counter += 1

        if os.path.exists(src_path):
            shutil.move(src_path, target_path)
            logger.info(f"Failed import moved to: {target_path}")
        else:
            logger.warning(f"Failed import source not found: {src_path}")

    except Exception:
        logger.exception(f"Error moving failed import from {src_path}")


def validate_metadata(file_path: str, book_title: str, book_id: int, readarr_client: Any) -> bool:
    """
    Validate file metadata against Readarr book info.
    Returns True if validation passes or is skipped for the file type, False otherwise.
    """
    extension = file_path.split(".")[-1].lower()
    match = False

    # Enhanced metadata validation with better error handling
    if extension in ["azw3", "mobi"]:
        try:
            logger.info(f"Reading MOBI/AZW3 metadata from: {file_path}")
            metadata = MobiHeader(file_path)
            isbn = metadata.get_exth_value_by_id(104)

            if isbn is not None:
                logger.info(f"Found ISBN in metadata: {isbn}")
                try:
                    book_lookup = readarr_client.lookup(term=f"isbn:{str(isbn).strip()}")
                    if book_lookup and len(book_lookup) > 0:
                        book_to_test = book_lookup[0]["id"]
                        if book_to_test == book_id:
                            logger.info("ISBN matches book ID - validation passed")
                            match = True
                        else:
                            logger.warning(f"ISBN mismatch: expected {book_id}, got {book_to_test}")
                            match = True
                    else:
                        logger.warning(f"No book found for ISBN {isbn} - cannot verify")
                        match = False
                except Exception as e:
                    logger.error(f"Error looking up ISBN {isbn}: {e}")
                    match = False
            else:
                logger.warning("No ISBN found in metadata - cannot verify")
                match = False

        except Exception as e:
            logger.error(f"Error reading MOBI/AZW3 metadata: {e}")
            match = False

    elif extension == "epub":
        try:
            logger.info(f"Reading EPUB metadata from: {file_path}")
            metadata = ebookmeta.get_metadata(file_path)
            title = metadata.title

            if title:
                logger.info(f"Found title in metadata: '{title}'")
                logger.info(f"Expected title: '{book_title}'")

                # Enhanced title matching
                diff = difflib.SequenceMatcher(None, title, book_title).ratio()
                logger.info(f"Exact title match ratio: {diff:.3f}")

                normalized_title = re.sub(r"[^\w\s]", "", title.lower())
                normalized_book_title = re.sub(r"[^\w\s]", "", book_title.lower())
                normalized_diff = difflib.SequenceMatcher(None, normalized_title, normalized_book_title).ratio()
                logger.info(f"Normalized title match ratio: {normalized_diff:.3f}")

                title_words = set(title.lower().split())
                book_title_words = set(book_title.lower().split())
                word_intersection = len(title_words.intersection(book_title_words))
                word_union = len(title_words.union(book_title_words))
                word_similarity = word_intersection / word_union if word_union > 0 else 0
                logger.info(f"Word-based similarity: {word_similarity:.3f}")

                if diff > 0.8 or normalized_diff > 0.85 or word_similarity > 0.7:
                    logger.info("Title validation passed")
                    match = True
                else:
                    logger.warning(f"Title validation failed - insufficient similarity")
                    match = False
            else:
                logger.warning("No title found in EPUB metadata - cannot verify")
                match = False

        except Exception as e:
            logger.error(f"Error reading EPUB metadata: {e}")
            match = False

    else:
        logger.info(f"File type {extension} - skipping metadata validation")
        match = True

    return match


def organize_file(source_path: str, target_folder: str, filename: str, original_folder: str) -> bool:
    """
    Organize file into author folder and clean up source directory.
    Returns True if successful, False on error.
    """
    try:
        # Create target directory
        if not os.path.exists(target_folder):
            logger.info(f"Creating author directory: {target_folder}")
            os.makedirs(target_folder, exist_ok=True)

        target_file_path = os.path.join(target_folder, filename)

        if os.path.exists(source_path) and not os.path.exists(target_file_path):
            logger.info(f"Moving file from {source_path} to {target_file_path}")
            shutil.move(source_path, target_file_path)
            logger.info("File moved successfully")

            # Clean up source directory if empty
            try:
                if os.path.exists(original_folder) and not os.listdir(original_folder):
                    logger.info(f"Removing empty source directory: {original_folder}")
                    shutil.rmtree(original_folder)
            except OSError as e:
                logger.warning(f"Could not remove source directory {original_folder}: {e}")

            return True
        else:
            if not os.path.exists(source_path):
                logger.warning(f"Source file no longer exists: {source_path}")
            if os.path.exists(target_file_path):
                logger.warning(f"Target file already exists: {target_file_path}")
            return False

    except Exception as e:
        logger.error(f"Failed to organize file: {e}")
        return False


def trigger_imports(readarr_client: Any, readarr_download_dir: str, author_folders: list) -> list:
    """
    Trigger Readarr scan commands for processed author folders.
    Returns a list of command objects.
    """
    commands = []
    if not author_folders:
        return commands

    logger.info("Starting Readarr import commands...")
    for author_folder in author_folders:
        try:
            download_dir = os.path.join(readarr_download_dir, author_folder)
            logger.info(f"Importing from: {download_dir}")

            command = readarr_client.post_command(name="DownloadedBooksScan", path=download_dir)
            commands.append(command)
            logger.info(f"Import command created - ID: {command['id']} for folder: {author_folder}")

        except Exception:
            logger.exception(f"Failed to create import command for {author_folder}")

    if commands:
        print_import_summary(commands)

    return commands


def monitor_imports(readarr_client: Any, commands: list) -> None:
    """Monitor progress of Readarr import commands and report results."""
    if not commands:
        return

    logger.info("Monitoring import progress...")
    while True:
        completed_count = 0

        for task in commands:
            try:
                current_task = readarr_client.get_command(task["id"])
                if current_task["status"] in ["completed", "failed"]:
                    completed_count += 1
            except Exception as e:
                logger.error(f"Error checking task {task['id']}: {e}")
                completed_count += 1  # Count as completed to avoid infinite loop

        if completed_count == len(commands):
            break

        time.sleep(2)

    # Report final results
    logger.info("Import Results:")
    for task in commands:
        try:
            current_task = readarr_client.get_command(task["id"])
            status = current_task.get("status", "unknown")

            if "body" in current_task and "path" in current_task["body"]:
                path = current_task["body"]["path"]
                folder_name = os.path.basename(path)
            else:
                folder_name = f"Task {task['id']}"

            if status == "completed":
                logger.info(f"{folder_name}: Import completed successfully")
            elif status == "failed":
                logger.error(f"{folder_name}: Import failed")
                if "message" in current_task:
                    logger.error(f"Error message: {current_task['message']}")

                # Move failed import
                if "body" in current_task and "path" in current_task["body"]:
                    move_failed_import(current_task["body"]["path"])
            else:
                logger.warning(f"{folder_name}: Import status unknown - {status}")

        except Exception as e:
            logger.error(f"Error processing task result {task['id']}: {e}")


def process_imports(ctx: Any, grab_list: list):
    """Process downloaded files, validate metadata, and trigger Readarr import"""
    print_section_header("METADATA VALIDATION & IMPORT PHASE")

    readarr_disable_sync = ctx.config.getboolean("Readarr", "disable_sync", fallback=False)
    slskd_download_dir = ctx.config["Slskd"]["download_dir"]
    readarr_download_dir = ctx.config["Readarr"]["download_dir"]
    readarr = ctx.readarr

    # Check if sync is disabled first
    if readarr_disable_sync:
        logger.warning("Readarr sync is disabled in config. Skipping import phase.")
        logger.info(f"Files downloaded but not imported. Check download directory: {slskd_download_dir}")
        return

    os.chdir(slskd_download_dir)
    logger.info(f"Changed to download directory: {slskd_download_dir}")

    grab_list.sort(key=operator.itemgetter("author_name"))
    failed_imports = []

    for book_download in grab_list:
        try:
            author_name = book_download["author_name"]
            author_name_sanitized = sanitize_folder_name(author_name)
            folder = book_download["dir"]
            filename = book_download["filename"]
            book_title = book_download["title"]
            book_id = book_download["bookId"]

            logger.info(f"Processing file: {filename} for book: {book_title}")
            source_file_path = os.path.join(folder, filename)

            if not os.path.exists(source_file_path):
                logger.error(f"Source file not found: {source_file_path}")
                failed_imports.append((folder, filename, author_name_sanitized, f"Source file not found: {source_file_path}"))
                continue

            # 1. Validate Metadata
            if validate_metadata(source_file_path, book_title, book_id, readarr):
                # 2. Organize File
                if organize_file(source_file_path, author_name_sanitized, filename, folder):
                    logger.info(f"Successfully processed {filename}")
                else:
                    failed_imports.append((folder, filename, author_name_sanitized, "Failed to organize file"))
            else:
                logger.warning(f"Metadata validation failed for {filename}")
                failed_imports.append((folder, filename, author_name_sanitized, "Metadata validation failed"))

        except Exception:
            logger.exception(f"Unexpected error processing {book_download.get('filename', 'unknown')}")
            failed_imports.append((book_download.get("dir", "unknown"), book_download.get("filename", "unknown"), book_download.get("author_name", "unknown"), "Unexpected error"))

    # Handle failed imports
    if failed_imports:
        logger.warning(f"{len(failed_imports)} files failed validation/processing")

        for folder, filename, author_name_sanitized, error_reason in failed_imports:
            logger.warning(f"Failed: {filename} - Reason: {error_reason}")

            failed_imports_dir = "failed_imports"
            try:
                if not os.path.exists(failed_imports_dir):
                    os.makedirs(failed_imports_dir)
                    logger.info(f"Created failed imports directory: {failed_imports_dir}")

                target_path = os.path.join(failed_imports_dir, author_name_sanitized)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(failed_imports_dir, f"{author_name_sanitized}_{counter}")
                    counter += 1

                os.makedirs(target_path, exist_ok=True)

                source_file_path = os.path.join(folder, filename)
                if os.path.exists(source_file_path):
                    shutil.move(source_file_path, target_path)
                    logger.info(f"Moved failed file to: {target_path}")

                    if os.path.exists(folder) and not os.listdir(folder):
                        shutil.rmtree(folder)

            except Exception as e:
                logger.error(f"Error handling failed import for {filename}: {e}")

    # Get list of successfully processed author folders
    try:
        author_folders = next(os.walk("."))[1]
        author_folders = [f for f in author_folders if f != "failed_imports"]
    except Exception as e:
        logger.error(f"Error listing directories: {e}")
        author_folders = []

    # 3. Trigger & 4. Monitor Imports
    if author_folders:
        commands = trigger_imports(readarr, readarr_download_dir, author_folders)
        if commands:
            monitor_imports(readarr, commands)
        else:
            logger.warning("No import commands were created successfully")
    else:
        logger.warning("No author folders found to import")
