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

logger = logging.getLogger('soularr')
#Allows backwards compatability for users updating an older version of Soularr
#without using the new [Logging] section in the config.ini file.
DEFAULT_LOGGING_CONF = {
    'level': 'INFO',
    'format': '[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s',
    'datefmt': '%Y-%m-%dT%H:%M:%S%z',
}

def album_match(target, slskd_tracks, username, filetype):

    book_title = target['book']['title']
    artist_name = target['author']['authorName']

    best_match = 0.0
    current_match = None

    for slskd_track in slskd_tracks:

        book_filename = book_title+" - "+artist_name + "." + filetype.split(" ")[0]
        slskd_filename = slskd_track['filename']

        logger.info(f"Checking ratio on {slskd_filename} vs wanted {book_filename}")
        #Try to match the ratio with the exact filenames
        ratio = difflib.SequenceMatcher(None, book_filename, slskd_filename).ratio()


        #If ratio is a bad match try and split off (with " " as the seperator) the garbage at the start of the slskd_filename and try again
        ratio = check_ratio(" ", ratio, book_filename, slskd_filename)
        #Same but with "_" as the seperator
        ratio = check_ratio("_", ratio, book_filename, slskd_filename)

        #Same checks but preappend album name.
        book_filename = artist_name+" - "+book_title + "." + filetype.split(" ")[0]
        ratio = check_ratio("", ratio ,  book_filename, slskd_filename)
        ratio = check_ratio(" ", ratio,  book_filename, slskd_filename)
        ratio = check_ratio("_", ratio,  book_filename, slskd_filename)

        if ratio > best_match:
            logger.info(f"Current best match is {ratio}")
            best_match = ratio
            current_match = slskd_track


    logger.info(f"Username is {username}")
    logger.info(f"Ratio is {best_match}")

    if (current_match != None) and (username not in ignored_users) and (best_match >= minimum_match_ratio):
        logger.info(f"Found match from user: {username} for book! Track attributes: {filetype}")
        logger.info(f"Average sequence match ratio: {best_match}")
        logger.info("SUCCESSFUL MATCH")
        logger.info("-------------------")
        return current_match

    return None


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

    return_data =	{
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
            for username in dir_cache:
                if not allowed_filetype in dir_cache[username]:
                    continue
                logger.info(f"Parsing result from user: {username}")
                for file_dir in dir_cache[username][allowed_filetype]:

                    if username not in search_cache:
                        logger.info(f"Add user to cache: {username}")
                        search_cache[username] = {}

                    if file_dir not in search_cache[username]:
                        logger.info(f"Cache miss user: {username}   folder: {file_dir}")
                        try:
                            directory = slskd.users.directory(username = username, directory = file_dir)
                        except:
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
    query = book['authorTitle']

    logger.info(f"Searching album: {query}")
    search = slskd.searches.search_text(searchText = query,
                                        searchTimeout = config.getint('Search Settings', 'search_timeout', fallback=5000),
                                        filterResponses = True,
                                        maximumPeerQueueLength = config.getint('Search Settings', 'maximum_peer_queue', fallback=50),
                                        minimumPeerUploadSpeed = config.getint('Search Settings', 'minimum_peer_upload_speed', fallback=0))

    time.sleep(10)
    while True:
        state = slskd.searches.state(search['id'],False)['state']
        if state != 'InProgress':
            break
        time.sleep(1)

    logger.info(f"Search returned {len(slskd.searches.search_responses(search['id']))} results")

    dir_cache = {}
    search_cache = {}

    for result in slskd.searches.search_responses(search['id']):
        username = result['username']
        if username not in dir_cache:
            dir_cache[username] = {}
        logger.info(f"Truncating directory count of user: {username}")
        init_files = result['files']
        for file in init_files:
            file_dir = file['filename'].rsplit('\\',1)[0]
            for allowed_filetype in allowed_filetypes:
                if verify_filetype(file, allowed_filetype):
                    if allowed_filetype not in dir_cache[username]:
                        dir_cache[username][allowed_filetype] = []
                    if file_dir not in dir_cache[username][allowed_filetype]:
                        dir_cache[username][allowed_filetype].append(file_dir)
    
    for allowed_filetype in allowed_filetypes:
        logger.info(f"Serching for matches with selected attributes: {allowed_filetype}")
        found, username, directory, file_dir, file = check_for_match(dir_cache, search_cache, target, allowed_filetype)       
        if found:
            if download_album(target, username, file_dir, directory, retry_list, grab_list, file):
                if delete_searches:
                    slskd.searches.delete(search['id'])
                return True, artist_name
            else:
                continue

    if delete_searches:
        slskd.searches.delete(search['id'])
               
    return False, artist_name


def download_album(target, username, file_dir, directory, retry_list, grab_list,file):

    #if download_filtering: 
    #    logger.info(f"Processing Download Filtering")
    #    if use_extension_whitelist:
    #        logger.info(f"Using extensions_whitelist: {use_extension_whitelist}")
    #        whitelist = copy.deepcopy(extensions_whitelist)
    #    else:
    #        whitelist = []
    #    whitelist.append(allowed_filetype.split(" ")[0])
    #    unwanted = []
    #    logger.info(f"Accepted extensions: {whitelist}")
    #    for file in directory['files']:
    #        match = False
    #        for extension in whitelist:
    #            if file['filename'].split(".")[-1].lower() == extension.lower():
    #                match = True
    #        if not match:
    #            unwanted.append(file['filename'])
    #            logger.info(f"File: {file['filename']} is unwanted")
    #    if len(unwanted) > 0:
    #        temp = []
    #        for file in directory['files']:
    #            if file['filename'] not in unwanted:
    #                logger.info(f"File: {file['filename']} added to modified directory listing")
    #                temp.append(file)
    #        directory['files'] = temp

    directory['files'] = [file]
    filename = file['filename']

    for i in range(0,len(directory['files'])):
       directory['files'][i]['filename'] = file_dir + "\\" + directory['files'][i]['filename']

    folder_data = {
        "artist_name": target['author']['authorName'],
        "title": target['book']['title'],
        'bookId': target['book']['id'],
        "dir": file_dir.split("\\")[-1],
        "username": username,
        "directory": directory,
        "filename": filename,
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
        

    # Delete the search from SLSKD DB
    return False


def is_blacklisted(title: str) -> bool:
    blacklist = config.get('Search Settings', 'title_blacklist', fallback='').lower().split(",")
    for word in blacklist:
        if word != '' and word in title.lower():
            logger.info(f"Skipping {title} due to blacklisted word: {word}")
            return True
    return False


def grab_most_wanted(download_targets):
    grab_list = []
    failed_download = 0
    success = False
    retry_list = {}

    for target in download_targets:
        book = target['book']
        author = target['author']
        artist_name = author['authorName']

        success = search_and_download(grab_list, target, retry_list)


        #if not success and config.getboolean('Search Settings', 'search_for_tracks', fallback=True):
        #    for media in release['media']:
        #        tracks = []
        #        for track in all_tracks:
        #            if track['mediumNumber'] == media['mediumNumber']:
        #                tracks.append(track)

        #        for track in tracks:
        #            if is_blacklisted(track['title']):
        #                continue

        #            if len(track['title']) == 1:
        #                query = artist_name + " " + track['title']
        #            else:
        #                query = artist_name + " " + track['title'] if config.getboolean('Search Settings', 'track_prepend_artist', fallback=True) else track['title']

        #            logger.info(f"Searching track: {query}")
        #            success = search_and_download(grab_list, query, tracks, track, artist_name, release,retry_list)

        #            if success:
        #                break

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
                logger.error(f"Failed to grab album: {book['title']} for artist: {artist_name}")

            failed_download += 1

        #success = False

    logger.info("Downloads added:")
    downloads = slskd.transfers.get_all_downloads()

    for download in downloads:
        username = download['username']
        for dir in download['directories']:
            logger.info(f"Username: {username} Directory: {dir['directory']}")
    logger.info("-------------------")
    logger.info(f"Waiting for downloads... monitor at: {''.join([slskd_host_url, slskd_url_base, 'downloads'])}")

    time_count = 0
    previous_total = sys.maxsize

    while True:
        unfinished = 0
        total_remaining = 0
        for artist_folder in list(grab_list):
            username, dir = artist_folder['username'], artist_folder['directory']
            downloads = slskd.transfers.get_downloads(username)

            for directory in downloads["directories"]:
                if directory["directory"] == dir["name"]:
                    for file in directory['files']:
                        total_remaining += file['bytesRemaining']
                    # Generate list of errored or failed downloads
                    errored_files = [file for file in directory["files"] if file["state"] in [
                        'Completed, Cancelled',
                        'Completed, TimedOut',
                       #'Completed, Errored',
                        'Completed, Rejected',
                    ]]

                    for file in directory["files"]:
                        if file["state"] == 'Completed, Errored':
                            logger.info(f"File: {file['filename']} has an error.")
                            if file['filename'] in retry_list[username]:
                                retry_list[username][file['filename']] += 1
                            if retry_list[username][file['filename']] > 2:
                                logger.info(f"Too many retries: {file['filename']}")
                                errored_files.append(file)
                            else:
                                logger.info(f"Retry file: {file['filename']} ")
                                slskd.transfers.enqueue(username = username, files = [file])

                    # Generate list of downloads still pending
                    pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]

                    # If we have errored files, cancel and remove ALL files so we can retry next time
                    if len(errored_files) > 0:
                        logger.error(f"FAILED: Username: {username} Directory: {dir['name']}")
                        cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                        grab_list.remove(artist_folder)
                        for file in directory['files']:
                            del retry_list[username][file['filename']]
                        if len(retry_list[username]) <= 0:
                            del retry_list[username]
                    elif len(pending_files) > 0:
                        unfinished += 1

        if unfinished == 0:
            logger.info("All tracks finished downloading!")
            time.sleep(5)
            retry_list={}
            break
        
        if previous_total > total_remaining:
            previous_total = total_remaining
        else:
            time_count += 10

        if(time_count > stalled_timeout):
            logger.info("Stall timeout reached! Removing stuck downloads...")

            for directory in downloads["directories"]:
                if directory["directory"] == dir["name"]:
                    #TODO: This does not seem to account for directories where the whole dir is stuck as queued.
                    #Either it needs to account for those or maybe soularr should just force clear out the downloads screen when it exits.
                    pending_files = [file for file in directory["files"] if not 'Completed' in file["state"]]

                    if len(pending_files) > 0:
                        logger.error(f"Removing Stalled Download: Username: {username} Directory: {dir['name']}")
                        cancel_and_delete(artist_folder['dir'], artist_folder['username'], directory["files"])
                        grab_list.remove(artist_folder)

            logger.info("All tracks finished downloading!")
            time.sleep(5)
            break

        time.sleep(10)

    os.chdir(slskd_download_dir)
    commands = []
    grab_list.sort(key=operator.itemgetter('artist_name'))

    for artist_folder in grab_list:
        artist_name = artist_folder['artist_name']
        artist_name_sanitized = sanitize_folder_name(artist_name)

        folder = artist_folder['dir']
        filename = artist_folder['filename']

        logger.info(f"Ensuring correct match on {filename}")
        extention = filename.split('.')[-1]
        match = False
        if extention.lower() in ['azw3', 'mobi']:
            try:
                metadata = MobiHeader(os.path.join(folder,filename))
                isbn = metadata.get_exth_value_by_id(104)
                if isbn != None:
                    book_to_test = readarr.lookup(term="isbn:"+str(isbn).strip())[0]['id']
                    if book_to_test == artist_folder['bookId']:
                        logger.info("Match of ISBN/Book ID")
                        match = True
                    else:
                        match = False
            except:
                match = True
        if extention.lower() == 'epub':
            try:
                metadata = ebookmeta.get_metadata(os.path.join(folder,filename))
                title = metadata.title
                diff = difflib.SequenceMatcher(None, title, artist_folder['title']).ratio()
                if diff > 0.8:
                    logger.info(f"Actual metadata diff: {diff}")
                    match = True
                else:
                    match = False
            except:
                match = True
        else:
            match = True

        if match:

            if not os.path.exists(artist_name_sanitized):
                os.mkdir(artist_name_sanitized)

            if os.path.exists(os.path.join(folder,filename)) and not os.path.exists(os.path.join(artist_name_sanitized,filename)):
                shutil.move(os.path.join(folder,filename),artist_name_sanitized)

        if os.path.exists(folder):
            shutil.rmtree(folder)


    if lidarr_disable_sync:
        return failed_download

    artist_folders = next(os.walk('.'))[1]
    artist_folders = [folder for folder in artist_folders if folder != 'failed_imports']

    for artist_folder in artist_folders:
        download_dir = os.path.join(lidarr_download_dir,artist_folder)
        command = readarr.post_command(name = 'DownloadedBooksScan', path = download_dir)
        commands.append(command)
        logger.info(f"Starting Readarr import for: {artist_folder} ID: {command['id']}")

    while True:
        completed_count = 0
        for task in commands:
            current_task = readarr.get_command(task['id'])
            if current_task['status'] == 'completed' or current_task['status'] == 'failed':
                completed_count += 1
        if completed_count == len(commands):
            break
        time.sleep(2)

    for task in commands:
        current_task = readarr.get_command(task['id'])
        try:
            logger.info(f"{current_task['commandName']} {current_task['message']} from: {current_task['body']['path']}")

            if "Failed" in current_task['message']:
                move_failed_import(current_task['body']['path'])
        except:
            logger.error("Error printing lidarr task message. Printing full unparsed message.")
            logger.error(current_task)

    return failed_download


def move_failed_import(src_path):
    failed_imports_dir = "failed_imports"

    if not os.path.exists(failed_imports_dir):
        os.makedirs(failed_imports_dir)

    folder_name = os.path.basename(src_path)
    target_path = os.path.join(failed_imports_dir, folder_name)

    counter = 1
    while os.path.exists(target_path):
        target_path = os.path.join(failed_imports_dir, f"{folder_name}_{counter}")
        counter += 1

    if os.path.exists(folder_name):
        shutil.move(folder_name, target_path)
        logger.info(f"Failed import moved to: {target_path}")


def is_docker():
    return os.getenv('IN_DOCKER') is not None


def setup_logging(config):
    if 'Logging' in config:
        log_config = config['Logging']
    else:
        log_config = DEFAULT_LOGGING_CONF
    logging.basicConfig(**log_config)   # type: ignore


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
    page_size = config.getint('Search Settings', 'number_of_albums_to_grab', fallback=10)
    remove_wanted_on_failure = config.getboolean('Search Settings', 'remove_wanted_on_failure', fallback=True)

    download_filtering = config.getboolean('Download Settings', 'download_filtering', fallback=False)
    use_extension_whitelist = config.getboolean('Download Settings', 'use_extension_whitelist', fallback=False)
    extensions_whitelist = config.get('Download Settings', 'extensions_whitelist', fallback='txt,nfo,jpg').split(',')

    setup_logging(config)


    slskd = slskd_api.SlskdClient(host=slskd_host_url, api_key=slskd_api_key, url_base=slskd_url_base)
    readarr = ReadarrAPI(readarr_host_url, readarr_api_key)
    wanted_books = []
#    book = readarr.lookup(term="isbn:9781444006728")
#    for item in book:
#        if 'book' in item:
#            pprint.pprint(item['book'])
#            replacement = item['book']
#
#    result = readarr.get_manual_import(folder='/mnt/ceph/media/downloads/slskd/failed_imports/Brandon Sanderson/')
#    #pprint.pprint(result)
#    import_files = []
#    for file in result:
#        print(file.keys())
#        new_file = {}
#        new_file['path'] = file['path']
#        new_file['quality'] = file['quality']
#        new_file['authorId'] = replacement['authorId']
#        new_file['bookId'] = replacement['id']
#        new_file['foreignEditionId'] = replacement['foreignEditionId']
#        new_file['indexerFlags'] = 0
#        new_file['disableReleaseSwitching'] = True
#        import_files.append(new_file)
#        pprint.pprint(new_file)
#
#
#
#
##dict_keys(['path', 'name', 'size', 'author', 'book', 'foreignEditionId', 'quality', 'qualityWeight', 'indexerFlags', 'rejections', 'audioTags', 'additionalFile', 'replaceExistingFiles', 'disableReleaseSwitching', 'id'])
#
#    
#
## {"name":"ManualImport",
##   "files":[{"path":"/books/Brandon Sanderson/Alcatraz versus the Knights of Crystallia (124)/Alcatraz versus the Knights of Crystallia - Brandon Sanderson.epub",
##              "authorId":7,
##              "bookId":133,
##              "foreignEditionId":"21053571",
##              "quality":{"quality":{"id":3,"name":"EPUB"},"revision":{"version":1,"real":0,"isRepack":false}},
##              "indexerFlags":0,
##              "disableReleaseSwitching":false}],
##   "importMode":"auto",
##   "replaceExistingFiles":false}
#
#    command = readarr.post_command(name = 'ManualImport', files=import_files, importMode='auto', replaceExistingFiles=False)
#
#    #result[0]['book'] = replacement
#
    #result = readarr.upd_manual_import(data=result)


    try:
        for source in search_sources:
            logging.debug(f'Getting records from {source}')
            missing = source == 'missing'
            wanted_books.extend(get_books(missing))
    except ValueError as ex:
        logger.error(f'An error occured: {ex}')
        logger.error('Exiting...')
        sys.exit(0)
    download_targets = []
    if len(wanted_books) > 0:
        for book in wanted_books:
            authorID = book['authorId']
            author = readarr.get_author(authorID)
            qprofile = readarr.get_quality_profile(author['qualityProfileId'])
            download_targets.append({'book':book,'author':author,'filetypes':qprofile})


    if len(download_targets) > 0:
        try:
            failed = grab_most_wanted(download_targets)
        except Exception:
            logger.error(traceback.format_exc())
            logger.error("\n Fatal error! Exiting...")

            if os.path.exists(lock_file_path) and not is_docker():
                os.remove(lock_file_path)
            sys.exit(0)
        if failed == 0:
            logger.info("Readarr_Soul finished. Exiting...")
            slskd.transfers.remove_completed_downloads()
        else:
            if remove_wanted_on_failure:
                logger.info(f'{failed}: releases failed and were removed from wanted list. View "failure_list.txt" for list of failed albums.')
            else:
                logger.info(f"{failed}: releases failed while downloading and are still wanted.")
            slskd.transfers.remove_completed_downloads()
    else:
        logger.info("No releases wanted. Exiting...")

finally:
    # Remove the lock file after activity is done
    if os.path.exists(lock_file_path) and not is_docker():
        os.remove(lock_file_path)
