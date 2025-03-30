import contextlib
import time

import pytest
import responses
from responses import matchers

from pyarr.exceptions import PyarrMissingArgument, PyarrResourceNotFound
from pyarr.readarr import ReadarrAPI

from tests import (
    READARR_AUTHOR_ID,
    READARR_AUTHOR_TERM,
    READARR_GOODREADS_ID,
    load_fixture,
)


def test_add_root_folder(readarr_client: ReadarrAPI):
    qual_profile = readarr_client.get_quality_profile()
    meta_profile = readarr_client.get_metadata_profile()

    data = readarr_client.add_root_folder(
        name="test",
        path="/defaults/",
        default_quality_profile_id=qual_profile[0]["id"],
        default_metadata_profile_id=meta_profile[0]["id"],
    )
    assert isinstance(data, dict)


def test_get_root_folder(readarr_client: ReadarrAPI):
    data = readarr_client.get_root_folder()
    assert isinstance(data, list)

    data = readarr_client.get_root_folder(data[0]["id"])
    assert isinstance(data, dict)


def test_get_quality_profile(readarr_client: ReadarrAPI):
    data = readarr_client.get_quality_profile()
    assert isinstance(data, list)

    data = readarr_client.get_quality_profile(data[0]["id"])
    assert isinstance(data, dict)


def test_lookup(readarr_client: ReadarrAPI):
    data = readarr_client.lookup(term=f"edition:{READARR_GOODREADS_ID}")
    assert isinstance(data, list)


def test_lookup_book(readarr_client: ReadarrAPI):
    data = readarr_client.lookup_book(term=f"edition:{READARR_GOODREADS_ID}")
    assert isinstance(data, list)


def test_lookup_author(readarr_client: ReadarrAPI):
    data = readarr_client.lookup_author(term=READARR_AUTHOR_TERM)
    assert isinstance(data, list)


def test_add_book(readarr_client: ReadarrAPI):
    qual_profile = readarr_client.get_quality_profile()
    meta_profile = readarr_client.get_metadata_profile()

    items = readarr_client.lookup(f"edition:{READARR_GOODREADS_ID}")
    for item in items:
        if "book" in item:
            book = item["book"]
            data = readarr_client.add_book(
                book=book,
                root_dir="/defaults/",
                quality_profile_id=qual_profile[0]["id"],
                metadata_profile_id=meta_profile[0]["id"],
            )
            break
    assert isinstance(data, dict)
    assert data["title"] == book["title"]


def test_create_tag(readarr_client: ReadarrAPI):
    data = readarr_client.create_tag(label="test")
    assert isinstance(data, dict)
    assert data["label"] == "test"


def test_get_tag(readarr_client: ReadarrAPI):
    data = readarr_client.get_tag()
    assert isinstance(data, list)

    data = readarr_client.get_tag(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_add_metadata_profile(readarr_client: ReadarrAPI):
    data = readarr_client.add_metadata_profile(
        name="TestProfile",
        min_popularity=0,
        skip_missing_date=False,
        skip_missing_isbn=False,
        skip_parts_and_sets=False,
        skip_series_secondary=False,
        allowed_languages="eng",
        min_pages=0,
    )
    assert isinstance(data, dict)
    assert data["name"] == "TestProfile"


def test_add_quality_profile(readarr_client: ReadarrAPI):
    data = readarr_client.add_quality_profile(
        name="TestProfile",
        upgrades_allowed=False,
        cutoff=4,
        items=[
            {
                "quality": {"id": 0, "name": "Unknown Text"},
                "items": [],
                "allowed": False,
            },
            {"quality": {"id": 1, "name": "PDF"}, "items": [], "allowed": False},
            {"quality": {"id": 2, "name": "MOBI"}, "items": [], "allowed": True},
            {"quality": {"id": 3, "name": "EPUB"}, "items": [], "allowed": True},
            {"quality": {"id": 4, "name": "AZW3"}, "items": [], "allowed": True},
            {
                "quality": {"id": 13, "name": "Unknown Audio"},
                "items": [],
                "allowed": False,
            },
            {"quality": {"id": 10, "name": "MP3"}, "items": [], "allowed": False},
            {"quality": {"id": 12, "name": "M4B"}, "items": [], "allowed": False},
            {"quality": {"id": 11, "name": "FLAC"}, "items": [], "allowed": False},
        ],
        min_format_score=0,
        cutoff_format_score=0,
    )
    assert isinstance(data, dict)
    assert data["name"] == "TestProfile"


def test_add_release_profile(readarr_client: ReadarrAPI):
    tags = readarr_client.get_tag()

    data = readarr_client.add_release_profile(
        ignored=["testing"],
        required=["test2"],
        indexerId=0,
        tags=[tags[0]["id"]],
        enabled=False,
        includePreferredWhenRenaming=True,
    )
    assert isinstance(data, dict)


def test_add_delay_profile(readarr_client: ReadarrAPI):
    tags = readarr_client.get_tag()
    data = readarr_client.add_delay_profile(
        tags=[tags[0]["id"]],
        preferredProtocol="usenet",
        usenetDelay=10,
        torrentDelay=10,
        bypassIfHighestQuality=True,
        bypassIfAboveCustomFormatScore=True,
        minimumCustomFormatScore=10,
    )
    assert isinstance(data, dict)
    assert data["preferredProtocol"] == "usenet"
    assert data["usenetDelay"] == 10
    assert data["torrentDelay"] == 10
    assert data["bypassIfHighestQuality"] == True
    assert data["bypassIfAboveCustomFormatScore"] == True
    assert data["minimumCustomFormatScore"] == 10


def test_get_missing(readarr_client: ReadarrAPI):
    data = readarr_client.get_missing()
    assert isinstance(data, dict)

    data = readarr_client.get_missing(
        page=1,
        page_size=20,
        sort_key="Books.Id",
        sort_dir="ascending",
    )
    assert isinstance(data, dict)

    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_missing(sort_key="timeleft")
        assert False
    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_missing(sort_dir="default")
        assert False


def test_get_cutoff(readarr_client: ReadarrAPI):
    data = readarr_client.get_cutoff()
    assert isinstance(data, dict)

    data = readarr_client.get_cutoff(
        page=1,
        page_size=20,
        sort_key="Books.Id",
        sort_dir="ascending",
        monitored=True,
    )
    assert isinstance(data, dict)

    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_cutoff(sort_key="timeleft")
        assert False
    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_cutoff(sort_dir="default")
        assert False


def test_get_book(readarr_client: ReadarrAPI):
    data = readarr_client.get_book()
    assert isinstance(data, list)

    data = readarr_client.get_book(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_upd_book(readarr_client: ReadarrAPI):
    book = readarr_client.get_book()
    editions = readarr_client.get_edition(book[0]["id"])

    data = readarr_client.upd_book(book=book[0], editions=editions)
    assert isinstance(data, dict)


def test_get_edition(readarr_client: ReadarrAPI):
    book = readarr_client.get_book()

    data = readarr_client.get_edition(id_=book[0]["id"])
    assert isinstance(data, list)


def test_upd_book_monitor(readarr_client: ReadarrAPI):
    books = readarr_client.get_book()
    book_ids = [d.get("id") for d in books]

    data = readarr_client.upd_book_monitor(book_ids=book_ids, monitored=False)

    assert isinstance(data, list)
    assert data[0]["monitored"] == False


def test_add_author(readarr_client: ReadarrAPI):
    qual_profile = readarr_client.get_quality_profile()
    meta_profile = readarr_client.get_metadata_profile()

    items = readarr_client.lookup(f"author:{READARR_AUTHOR_ID}")
    for item in items:
        if "author" in item:
            author = item["author"]
            data = readarr_client.add_author(
                author=author,
                root_dir="/defaults/",
                quality_profile_id=qual_profile[0]["id"],
                metadata_profile_id=meta_profile[0]["id"],
            )
            break
        if item == items[-1]:
            assert False

    assert isinstance(data, dict)


def test_upd_author(readarr_client: ReadarrAPI):
    author = readarr_client.get_author()
    author[0]["monitored"] = True

    data = readarr_client.upd_author(id_=author[0]["id"], data=author[0])
    assert isinstance(data, dict)
    assert data["monitored"] == True


def test_get_author(readarr_client: ReadarrAPI):
    data = readarr_client.get_author()
    assert isinstance(data, list)

    data = readarr_client.get_author(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_get_metadata_profile(readarr_client: ReadarrAPI):
    data = readarr_client.get_metadata_profile()
    assert isinstance(data, list)

    data = readarr_client.get_metadata_profile(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_get_delay_profile(readarr_client: ReadarrAPI):
    data = readarr_client.get_delay_profile()
    assert isinstance(data, list)

    data = readarr_client.get_delay_profile(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_get_release_profile(readarr_client: ReadarrAPI):
    data = readarr_client.get_release_profile()
    assert isinstance(data, list)

    data = readarr_client.get_release_profile(id_=data[0]["id"])
    assert isinstance(data, dict)


def test_get_language(readarr_client: ReadarrAPI):
    data = readarr_client.get_language()
    assert isinstance(data, list)

    data = readarr_client.get_language(data[0]["id"])
    assert isinstance(data, dict)


def test_get_quality_profile_schema(readarr_client: ReadarrAPI):
    data = readarr_client.get_quality_profile_schema()
    assert isinstance(data, dict)


def test_get_history(readarr_client: ReadarrAPI):
    data = readarr_client.get_history()
    assert isinstance(data, dict)

    for key in ["id", "date", "eventType"]:
        data = readarr_client.get_history(
            page=1,
            page_size=10,
            sort_key=key,
            sort_dir="default",
        )
        assert isinstance(data, dict)

    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_history(sort_key="date")
        assert False

    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_client.get_history(sort_dir="descending")
        assert False


def test_get_log_file(readarr_client: ReadarrAPI):
    data = readarr_client.get_log_file()
    assert isinstance(data, list)


def test_get_metadata_provider(readarr_client: ReadarrAPI):
    data = readarr_client.get_metadata_provider()
    assert isinstance(data, dict)


def test_upd_metadata_provider(readarr_client: ReadarrAPI):
    provider = readarr_client.get_metadata_provider()
    data = readarr_client.upd_metadata_provider(data=provider)
    assert isinstance(data, dict)


def test_get_command(readarr_client: ReadarrAPI):
    # No args
    data = readarr_client.get_command()
    assert isinstance(data, list)

    # When an ID is supplied
    data = readarr_client.get_command(data[0]["id"])
    assert isinstance(data, dict)

    # when an incorrect ID is supplied, not found response
    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.get_command(4321)
        assert False


def test_post_command(readarr_client: ReadarrAPI):
    # ApplicationUpdateCheck
    data = readarr_client.post_command(name="ApplicationUpdateCheck")
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # AuthorSearch
    data = readarr_client.post_command(
        "AuthorSearch", authorId=readarr_client.get_author()[0]["id"]
    )
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # BookSearch
    data = readarr_client.post_command(
        "BookSearch", bookId=readarr_client.get_book()[0]["id"]
    )
    assert isinstance(data, dict)

    # RefreshAuthor
    data = readarr_client.post_command(
        "RefreshAuthor", authorId=readarr_client.get_author()[0]["id"]
    )
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # RefreshBook
    data = readarr_client.post_command(
        "RefreshBook", bookId=readarr_client.get_book()[0]["id"]
    )
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed" or "started"

    # RenameAuthor
    data = readarr_client.post_command(
        "RenameAuthor", authorIds=[readarr_client.get_author()[0]["id"]]
    )
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # RescanFolders
    data = readarr_client.post_command("RescanFolders")
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # RssSync
    data = readarr_client.post_command("RssSync")
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # Backup
    data = readarr_client.post_command("Backup")
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # MissingBookSearch
    data = readarr_client.post_command("MissingBookSearch")
    time.sleep(5)
    result = readarr_client.get_command(id_=data["id"])
    assert isinstance(data, dict)
    assert result["status"] == "completed"

    # RenameFiles
    data = readarr_client.post_command(
        "RenameFiles", authorId=readarr_client.get_author()[0]["id"], files=[1, 2, 3]
    )
    assert isinstance(data, dict)


@pytest.mark.usefixtures
@responses.activate
def test_get_queue(readarr_mock_client: ReadarrAPI):
    ## Using mock to avoid need to have actual downloads

    responses.add(
        responses.GET,
        "https://127.0.0.1:8787/api/v1/queue",
        headers={"Content-Type": "application/json"},
        body=load_fixture("readarr/queue.json"),
        status=200,
    )
    data = readarr_mock_client.get_queue()
    assert isinstance(data, dict)

    responses.add(
        responses.GET,
        "https://127.0.0.1:8787/api/v1/queue",
        match=[
            matchers.query_string_matcher(
                "page=2&pageSize=20&sortKey=Books.Id&sortDirection=ascending&includeUnknownAuthorItems=True&includeAuthor=True&includeBook=True"
            )
        ],
        headers={"Content-Type": "application/json"},
        body=load_fixture("readarr/queue.json"),
        status=200,
    )
    data = readarr_mock_client.get_queue(
        page=2,
        page_size=20,
        sort_key="Books.Id",
        sort_dir="ascending",
        unknown_authors=True,
        include_author=True,
        include_book=True,
    )
    assert isinstance(data, dict)

    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_mock_client.get_queue(sort_key="timeleft")
        assert False
    with contextlib.suppress(PyarrMissingArgument):
        data = readarr_mock_client.get_queue(sort_dir="default")
        assert False


# TODO: get correct fixture
@pytest.mark.usefixtures
@responses.activate
def test_get_manual_import(readarr_mock_client: ReadarrAPI):
    responses.add(
        responses.GET,
        "https://127.0.0.1:8787/api/v1/manualimport",
        match=[matchers.query_string_matcher("folder=/books/")],
        headers={"Content-Type": "application/json"},
        body=load_fixture("common/blank_list.json"),
        status=200,
    )
    data = readarr_mock_client.get_manual_import(folder="/books/")
    assert isinstance(data, list)

    responses.add(
        responses.GET,
        "https://127.0.0.1:8787/api/v1/manualimport",
        match=[
            matchers.query_string_matcher(
                "folder=/books/&downloadId=1&authorId=1&filterExistingFiles=True&replaceExistingFiles=True"
            )
        ],
        headers={"Content-Type": "application/json"},
        body=load_fixture("common/blank_list.json"),
        status=200,
    )
    data = readarr_mock_client.get_manual_import(
        folder="/books/",
        download_id=1,
        author_id=1,
        filter_existing_files=True,
        replace_existing_files=True,
    )
    assert isinstance(data, list)


# TODO: get correct fixture, confirm update returns dict
@pytest.mark.usefixtures
@responses.activate
def test_upd_manual_import(readarr_mock_client: ReadarrAPI):
    responses.add(
        responses.GET,
        "https://127.0.0.1:8787/api/v1/manualimport",
        match=[matchers.query_string_matcher("folder=/books/")],
        headers={"Content-Type": "application/json"},
        body=load_fixture("common/blank_list.json"),
        status=200,
    )
    man_import = readarr_mock_client.get_manual_import(folder="/books/")

    responses.add(
        responses.PUT,
        "https://127.0.0.1:8787/api/v1/manualimport",
        headers={"Content-Type": "application/json"},
        body=load_fixture("common/blank_dict.json"),
        status=200,
    )
    data = readarr_mock_client.upd_manual_import(data=man_import)
    assert isinstance(data, dict)


# DELETE ACTIONS MUST BE LAST


@pytest.mark.usefixtures
def test_del_book(readarr_client: ReadarrAPI):
    book = readarr_client.get_book()

    data = readarr_client.del_book(
        book[0]["id"], delete_files=True, import_list_exclusion=True
    )
    assert data.status_code == 200

    # Check that none existant tag throws error
    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.del_book(999)
        assert False


@pytest.mark.usefixtures
def test_del_author(readarr_client: ReadarrAPI):
    authors = readarr_client.get_author()

    for author in authors:
        data = readarr_client.del_author(
            author["id"], delete_files=True, import_list_exclusion=True
        )
        assert data.status_code == 200

    # Check that none existant tag throws error
    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.del_author(999)
        assert False


@pytest.mark.usefixtures
def test_del_tag(readarr_client: ReadarrAPI):
    tag = readarr_client.get_tag()

    data = readarr_client.del_tag(tag[0]["id"])
    assert isinstance(data, dict)

    # Check that none existant tag throws error
    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.del_tag(999)
        assert False


def test_del_root_folder(readarr_client: ReadarrAPI):
    root_folders = readarr_client.get_root_folder()

    # Check folder can be deleted
    data = readarr_client.del_root_folder(root_folders[0]["id"])
    assert data.status_code == 200

    # Check that none existant doesnt throw error
    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.del_root_folder(999)
        assert False


def test_del_quality_profile(readarr_client: ReadarrAPI):
    quality_profiles = readarr_client.get_quality_profile()

    for profile in quality_profiles:
        if profile["name"] == "eBook":
            # Check folder can be deleted
            data = readarr_client.del_quality_profile(profile["id"])
            assert data.status_code == 200

    # Check that none existant doesnt throw error
    data = readarr_client.del_quality_profile(999)
    assert data.status_code == 200


def test_del_release_profile(readarr_client: ReadarrAPI):
    profile = readarr_client.get_release_profile()

    # Check folder can be deleted
    data = readarr_client.del_release_profile(profile[0]["id"])
    assert data.status_code == 200

    # Check that none existant doesnt throw error
    data = readarr_client.del_release_profile(999)
    assert data.status_code == 200


def test_del_delay_profile(readarr_client: ReadarrAPI):
    profile = readarr_client.get_delay_profile()

    # Check folder can be deleted
    data = readarr_client.del_delay_profile(profile[1]["id"])
    assert data.status_code == 200

    # Check that none existant doesnt throw error
    data = readarr_client.del_delay_profile(999)
    assert data.status_code == 200


def test_del_metadata_profile(readarr_client: ReadarrAPI):
    profiles = readarr_client.get_metadata_profile()

    for profile in profiles:
        if profile["name"] == "Standard":
            data = readarr_client.del_metadata_profile(profile["id"])
            assert data.status_code == 200

    with contextlib.suppress(PyarrResourceNotFound):
        data = readarr_client.del_metadata_profile(999)
        assert False
