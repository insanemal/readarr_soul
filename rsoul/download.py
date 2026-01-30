import time
import os
import shutil
import logging
from typing import Any, Optional, Dict, List, Tuple
from .types import Book, Author, DownloadTarget, SlskdFile, SlskdDirectory, BookDownload, QualityProfile

logger = logging.getLogger(__name__)


def slskd_do_enqueue(slskd_client: Any, username: str, files: List[SlskdFile], file_dir: str) -> Optional[List[SlskdFile]]:
    """
    Takes a list of files to download and returns a list of files that were successfully added to the download queue
    It also adds to each file the details needed to track that specific file.
    """
    downloads: List[SlskdFile] = []
    try:
        enqueue = slskd_client.transfers.enqueue(username=username, files=files)
    except Exception:
        logger.error("Enqueue failed", exc_info=True)
        return None

    if enqueue:
        # Poll for downloads to appear (handle race conditions)
        for attempt in range(4):
            time.sleep(2)
            downloads = []  # Reset on each attempt
            try:
                download_list = slskd_client.transfers.get_downloads(username=username)
                for file in files:
                    for directory in download_list["directories"]:
                        # Match directory name (full path or basename)
                        if directory["directory"] == file_dir.split("\\")[-1] or directory["directory"] == file_dir:
                            for slskd_file in directory["files"]:
                                # Match filename (full path or basename)
                                target_filename = file["filename"]
                                target_basename = target_filename.split("\\")[-1]
                                slskd_filename = slskd_file["filename"]

                                if slskd_filename == target_filename or slskd_filename == target_basename:
                                    file_details = {}
                                    file_details["filename"] = file["filename"]
                                    file_details["id"] = slskd_file["id"]
                                    file_details["file_dir"] = file_dir
                                    file_details["username"] = username
                                    file_details["size"] = file["size"]
                                    downloads.append(file_details)

                # If we found downloads, return them immediately
                if downloads:
                    return downloads

            except Exception:
                logger.error("Error getting download list after enqueue", exc_info=True)
                if attempt == 3:
                    return None

        return None
    else:
        return None


def slskd_download_status(slskd_client: Any, downloads: List[SlskdFile]) -> bool:
    """
    Takes a list of files and gets the status of each file and packs it into the file object.
    """
    ok = True
    for file in downloads:
        try:
            status = slskd_client.transfers.get_download(file["username"], file["id"])
            file["status"] = status
        except Exception:
            logger.exception(f"Error getting download status of {file['filename']}")
            file["status"] = None
            ok = False
    return ok


def downloads_all_done(downloads: List[SlskdFile]) -> Tuple[bool, Optional[List[SlskdFile]], int]:
    """
    Checks the status of all the files in a book and returns a flag if all done as well
    as returning a list of files with errors to check and how many files are in "Queued, Remotely"
    """
    all_done = True
    error_list: List[SlskdFile] = []
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

    result_error_list: Optional[List[SlskdFile]] = error_list if len(error_list) > 0 else None
    return all_done, result_error_list, remote_queue


def download_book(
    slskd_client: Any,
    target: DownloadTarget,
    username: str,
    file_dir: str,
    directory: SlskdDirectory,
    retry_list: Dict[str, Any],
    grab_list: List[BookDownload],
    file: SlskdFile,
) -> bool:
    directory["files"] = [file]
    filename = file["filename"]

    for i in range(0, len(directory["files"])):
        if "\\" not in directory["files"][i]["filename"]:
            directory["files"][i]["filename"] = file_dir + "\\" + directory["files"][i]["filename"]

    # Use the new enqueue function that returns tracked file objects with IDs
    downloads = slskd_do_enqueue(slskd_client, username, directory["files"], file_dir)

    if downloads:
        folder_data = {
            "author_name": target["author"]["authorName"],
            "title": target["book"]["title"],
            "bookId": target["book"]["id"],
            "dir": file_dir.split("\\")[-1],
            "full_dir": file_dir,
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
        return False


def cancel_and_delete(slskd_client: Any, delete_dir: str, username: str, files: List[SlskdFile], download_base_dir: str) -> None:
    for file in files:
        slskd_client.transfers.cancel_download(username=username, id=file["id"])

    os.chdir(download_base_dir)
    if os.path.exists(delete_dir):
        shutil.rmtree(delete_dir)
