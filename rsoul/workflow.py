import time
import logging
import datetime
import os
from typing import Any, Dict, List, TYPE_CHECKING
from . import search, postprocess, download

if TYPE_CHECKING:
    from .config import Context

from .display import print_section_header, print_download_summary

logger = logging.getLogger(__name__)


def monitor_downloads(ctx: "Context", grab_list: List[Dict[str, Any]]) -> int:
    """
    Monitor the progress of downloads and handle retries or timeouts.
    """
    slskd = ctx.slskd
    stalled_timeout = int(ctx.config["Slskd"].get("stalled_timeout", 3600))
    remote_queue_timeout = int(ctx.config["Slskd"].get("remote_queue_timeout", 300))
    slskd_download_dir = ctx.config["Slskd"]["download_dir"]

    # Get initial download status
    downloads = slskd.transfers.get_all_downloads()
    print_download_summary(downloads)

    slskd_host_url = ctx.config["Slskd"]["host_url"]
    slskd_url_base = ctx.config["Slskd"].get("url_base", "/")
    logger.info(f"Waiting for downloads... monitor at: {''.join([slskd_host_url, slskd_url_base, 'downloads'])}")

    failed_download = 0

    while True:
        if not grab_list:
            break

        unfinished = 0

        # Iterate over a copy of the list so we can modify the original
        for book_download in list(grab_list):
            username = book_download["username"]

            # Update status for all files in this folder using ID-based tracking
            if not download.slskd_download_status(slskd, book_download["files"]):
                book_download["error_count"] += 1

            # Check overall status
            book_done, problems, remote_queued_count = download.downloads_all_done(book_download["files"])

            # Check Stalled Timeout (Total time since start)
            if (time.time() - book_download["count_start"]) >= stalled_timeout:
                logger.error(f"Timeout waiting for download: {book_download['title']} from {username}")
                download.cancel_and_delete(slskd, book_download["dir"], username, book_download["files"], slskd_download_dir)
                grab_list.remove(book_download)
                failed_download += 1
                continue

            # Check Remote Queue Timeout (Time stuck in remote queue)
            if remote_queued_count == len(book_download["files"]):
                if (time.time() - book_download["count_start"]) >= remote_queue_timeout:
                    logger.error(f"Remote queue timeout: {book_download['title']} from {username}")
                    download.cancel_and_delete(slskd, book_download["dir"], username, book_download["files"], slskd_download_dir)
                    grab_list.remove(book_download)
                    failed_download += 1
                    continue

            if not book_done:
                unfinished += 1

            # Handle Problems
            if problems:
                abort_book = False

                # Check if we should abort based on types of errors
                for prob_file in problems:
                    state = prob_file["status"]["state"]

                    # RETRY LOGIC
                    if state in ["Completed, Cancelled", "Completed, TimedOut", "Completed, Errored", "Completed, Aborted", "Completed, Rejected"]:
                        # Special handling for "Completed, Rejected"
                        if state == "Completed, Rejected":
                            if len(problems) == len(book_download["files"]):
                                logger.error(f"All files rejected by user {username}")
                                abort_book = True
                                break

                            # Check if we have retried too many times for rejections
                            if book_download["rejected_retries"] >= int(len(book_download["files"]) * 1.2):
                                logger.error(f"Too many rejection retries for {username}")
                                abort_book = True
                                break

                            book_download["rejected_retries"] += 1

                        # Locate the specific file in our main list to update its retry count
                        for track_file in book_download["files"]:
                            if track_file["filename"] == prob_file["filename"]:
                                if "retry" not in track_file:
                                    track_file["retry"] = 0

                                track_file["retry"] += 1

                                if track_file["retry"] < 5:
                                    logger.info(f"Retrying file: {track_file['filename']} (Attempt {track_file['retry']})")
                                    # Re-queue specific file
                                    requeue = download.slskd_do_enqueue(slskd, username, [track_file], book_download["dir"])

                                    if requeue:
                                        # Update ID
                                        track_file["id"] = requeue[0]["id"]
                                        # Reset status to None so we don't catch it again immediately
                                        track_file["status"] = None
                                        time.sleep(1)
                                    else:
                                        logger.warning(f"Failed to requeue {track_file['filename']}")
                                        abort_book = True
                                else:
                                    logger.error(f"Max retries reached for {track_file['filename']}")
                                    abort_book = True
                                break

                    if abort_book:
                        break

                if abort_book:
                    logger.error(f"Aborting download for {book_download['title']} from {username}")
                    download.cancel_and_delete(slskd, book_download["dir"], username, book_download["files"], slskd_download_dir)
                    grab_list.remove(book_download)
                    failed_download += 1
                    continue

        if unfinished == 0:
            logger.info("All downloads finished!")
            time.sleep(5)
            break

        time.sleep(10)

    return failed_download


def run_workflow(ctx: "Context", download_targets: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Main workflow: Search, Monitor, Import, and Cleanup.
    """
    grab_list: List[Dict[str, Any]] = []
    retry_list: Dict[str, Any] = {}
    failed_download = 0

    remove_wanted_on_failure = ctx.config.getboolean("Search Settings", "remove_wanted_on_failure", fallback=False)
    failure_file_path = os.path.join(ctx.config_dir, "failure_list.txt")

    print_section_header("🎯 STARTING SEARCH PHASE")

    for target in download_targets:
        book = target["book"]
        author = target["author"]
        author_name = author["authorName"]

        success = search.search_and_download(ctx, grab_list, target, retry_list)

        if not success:
            if remove_wanted_on_failure:
                logger.error(f"Failed to grab book: {book['title']} for author: {author_name}." + ' Failed book removed from wanted list and added to "failure_list.txt"')
                book["monitored"] = False
                # Use ctx.readarr for Readarr calls
                edition = ctx.readarr.get_edition(book["id"])
                ctx.readarr.upd_book(book=book, editions=edition)

                current_datetime = datetime.datetime.now()
                current_datetime_str = current_datetime.strftime("%d/%m/%Y %H:%M:%S")
                failure_string = current_datetime_str + " - " + author_name + ", " + book["title"] + "\n"

                with open(failure_file_path, "a") as file:
                    file.write(failure_string)
            else:
                logger.error(f"Failed to grab book: {book['title']} for author: {author_name}")

            failed_download += 1

    print_section_header("📥 DOWNLOAD MONITORING PHASE")
    failed_download += monitor_downloads(ctx, grab_list)

    # Import Phase
    postprocess.process_imports(ctx, grab_list)

    # Cleanup
    ctx.slskd.transfers.remove_completed_downloads()

    return {"failed_download": failed_download, "grabbed_count": len(grab_list)}
