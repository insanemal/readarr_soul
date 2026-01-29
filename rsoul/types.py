from typing import TypedDict, List, Optional, Any, Dict


class Book(TypedDict, total=False):
    title: str
    id: int
    authorId: int
    monitored: bool


class Author(TypedDict, total=False):
    authorName: str
    qualityProfileId: int


class QualityProfileItem(TypedDict):
    allowed: bool
    quality: Dict[str, Any]


class QualityProfile(TypedDict):
    items: List[QualityProfileItem]


class DownloadTarget(TypedDict):
    book: Book
    author: Author
    filetypes: QualityProfile


class SlskdFile(TypedDict, total=False):
    filename: str
    size: int
    id: Optional[str]
    status: Optional[Dict[str, Any]]
    retry: Optional[int]
    file_dir: Optional[str]
    username: Optional[str]


class SlskdDirectory(TypedDict):
    files: List[SlskdFile]
    name: str


class BookDownload(TypedDict):
    author_name: str
    title: str
    bookId: int
    dir: str
    username: str
    directory: SlskdDirectory
    filename: str
    files: List[SlskdFile]
    count_start: float
    rejected_retries: int
    error_count: int
