import time
import os
import shutil
import logging

logger = logging.getLogger(__name__)


def slskd_do_enqueue(slskd_client, username, files, file_dir):
    """
    Takes a list of files to download and returns a list of files that were successfully added to the download queue
    It also adds to each file the details needed to track that specific file.
    """
    downloads = []
    try:
        enqueue = slskd_client.transfers.enqueue(username=username, files=files)
    except Exception:
        logger.debug("Enqueue failed", exc_info=True)
        return None

    if enqueue:
        time.sleep(5)
        # Fetch downloads to get IDs
        try:
            download_list = slskd_client.transfers.get_downloads(username=username)
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


def slskd_download_status(slskd_client, downloads):
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


def downloads_all_done(downloads):
    """
    Checks the status of all the files in a book and returns a flag if all done as well
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


def download_book(slskd_client, target, username, file_dir, directory, retry_list, grab_list, file):
    directory["files"] = [file]
    filename = file["filename"]

    for i in range(0, len(directory["files"])):
        directory["files"][i]["filename"] = file_dir + "\\" + directory["files"][i]["filename"]

    # Use the new enqueue function that returns tracked file objects with IDs
    downloads = slskd_do_enqueue(slskd_client, username, directory["files"], file_dir)

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
        return False


def cancel_and_delete(slskd_client, delete_dir, username, files, download_base_dir):
    for file in files:
        slskd_client.transfers.cancel_download(username=username, id=file["id"])

    os.chdir(download_base_dir)
    if os.path.exists(delete_dir):
        shutil.rmtree(delete_dir)
