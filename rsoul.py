#!/usr/bin/env python

import sys
import argparse
import os
import configparser
import logging
from rich.console import Console

# Import from rsoul package
from readarr_api import ReadarrAPI
import slskd_api

from rsoul.config import Context, setup_logging, validate_config
from rsoul.display import print_startup_banner, console
from rsoul.utils import is_docker
from rsoul.workflow import run_workflow
from rsoul.search import get_books

logger = logging.getLogger("readarr_soul")


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="""Readarr Soul: Connect Readarr with Soulseek""")

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
    config_dir = args.config_dir

    # Path setup
    lock_file_path = os.path.join(config_dir, ".soularr.lock")
    config_file_path = os.path.join(config_dir, "config.ini")

    # Lock check
    if not is_docker() and os.path.exists(lock_file_path):
        console.print(f"readarr_soul instance is already running.", style="bold red")
        sys.exit(1)

    try:
        # Print banner
        print_startup_banner()

        if not is_docker():
            with open(lock_file_path, "w") as lock_file:
                lock_file.write("locked")

        # Load Config
        # Disable interpolation to make storing logging formats in the config file much easier
        config = configparser.ConfigParser(interpolation=None)

        if os.path.exists(config_file_path):
            config.read(config_file_path)
        else:
            if is_docker():
                console.print('Config file does not exist! Please mount "/data" and place your "config.ini" file there.', style="bold red")
            else:
                console.print("Config file does not exist! Please place it in the working directory.", style="bold red")

            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)
            sys.exit(0)

        # Setup Logging
        setup_logging(config)

        # Validate Config
        validate_config(config)

        # Extract Config Values
        slskd_api_key = config["Slskd"]["api_key"]
        slskd_host_url = config["Slskd"]["host_url"]
        slskd_url_base = config.get("Slskd", "url_base", fallback="/")

        readarr_api_key = config["Readarr"]["api_key"]
        readarr_host_url = config["Readarr"]["host_url"]

        # Search Settings
        search_type = config.get("Search Settings", "search_type", fallback="first_page").lower().strip()
        search_source = config.get("Search Settings", "search_source", fallback="missing").lower().strip()
        search_sources = [search_source]
        if search_sources[0] == "all":
            search_sources = ["missing", "cutoff_unmet"]

        page_size = config.getint("Search Settings", "number_of_books_to_grab", fallback=10)

        # Initialize Clients
        slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
        readarr = ReadarrAPI(readarr_host_url, readarr_api_key)

        # Initialize Context
        ctx = Context(config=config, slskd=slskd, readarr=readarr, config_dir=config_dir)

        # Fetch Wanted Books
        wanted_books = []
        try:
            for source in search_sources:
                logger.debug(f"Getting records from {source}")
                wanted_books.extend(get_books(ctx, source, search_type, page_size))
        except ValueError as ex:
            logger.error(f"An error occurred: {ex}")
            logger.error("Exiting...")
            sys.exit(0)

        # Construct Download Targets
        download_targets = []
        if len(wanted_books) > 0:
            console.print(f"\nFound {len(wanted_books)} wanted books to process", style="bold green")

            for book in wanted_books:
                try:
                    authorID = book["authorId"]
                    author = ctx.readarr.get_author(authorID)
                    qprofile = ctx.readarr.get_quality_profile(author["qualityProfileId"])
                    download_targets.append({"book": book, "author": author, "filetypes": qprofile})
                except Exception:
                    logger.exception(f"Error processing book {book.get('title', 'unknown')}")
                    continue

        # Run Workflow
        if len(download_targets) > 0:
            try:
                run_workflow(ctx, download_targets)
            except Exception:
                logger.exception("Fatal error encountered during workflow execution")
                sys.exit(1)
        else:
            console.print("No releases wanted. Nothing to do!", style="blue")
            logger.info("No releases wanted. Exiting...")

    except KeyboardInterrupt:
        console.print("\nOperation cancelled by user", style="bold yellow")
    except ValueError as e:
        logger.error(f"{e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("An unexpected error occurred")
    finally:
        # cleanup lock
        if os.path.exists(lock_file_path) and not is_docker():
            try:
                os.remove(lock_file_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
