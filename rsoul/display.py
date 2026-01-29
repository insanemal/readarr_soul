import os
import logging
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
            record.msg = f"{record.msg}"
        elif record.levelno >= logging.WARNING:
            record.msg = f"{record.msg}"
        elif record.levelno >= logging.INFO:
            if "SUCCESSFUL MATCH" in str(record.msg):
                record.msg = f"{record.msg}"
            elif "Searching book" in str(record.msg):
                record.msg = f"{record.msg}"
            elif "Starting Readarr import" in str(record.msg):
                record.msg = f"{record.msg}"
            elif "Downloads added" in str(record.msg):
                record.msg = f"{record.msg}"
            elif "All files finished downloading" in str(record.msg):
                record.msg = f"{record.msg}"
            else:
                record.msg = f"{record.msg}"

        super().emit(record)


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
        style = "yellow"
        search_text = f"Fallback Search: {query}"
    else:
        style = "blue"
        search_text = f"Main Search: {query}"

    # Force full width by removing width constraints and using ratio
    table = Table(show_header=False, box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("", style=style, ratio=1, min_width=20)
    table.add_column("", style="white", ratio=4)

    table.add_row("Query:", search_text)

    if status == "searching":
        table.add_row("Status:", "Searching...")
    else:
        table.add_row("Results:", f"{results_count} files found")

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

    table.add_row("User:", username)
    table.add_row("Directory:", dir_name.split("\\")[-1])
    table.add_row("Files:", f"{file_count} files")

    console.print(table)


def print_download_summary(downloads):
    """Print a formatted table of downloads using full width"""
    if not downloads:
        console.print("No downloads to process", style="red")
        return

    # Force full width with explicit width setting
    table = Table(title="Download Queue", box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("Username", style="cyan", ratio=1, min_width=15)
    table.add_column("Directory", style="magenta", ratio=3)

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
    table = Table(title="Import Operations", box=box.ROUNDED, expand=True, width=console.width)
    table.add_column("Author", style="green", ratio=2, min_width=20)
    table.add_column("Command ID", style="yellow", ratio=1, min_width=12)
    table.add_column("Status", style="white", ratio=1, min_width=10)

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

    table.add_row("File:", filename)
    table.add_row("User:", username)
    table.add_row("Match Ratio:", f"{ratio:.3f}")
    table.add_row("Type:", filetype)

    console.print(table, style="green")


def print_section_header(title, style="bold blue"):
    """Print a section header with styling using full width"""
    # Create a full-width header
    separator = "=" * console.width

    console.print(f"\n{separator}")
    console.print(f"  {title}", style=style)
    console.print(f"{separator}")


__all__ = [
    "console",
    "CustomRichHandler",
    "get_terminal_width",
    "print_startup_banner",
    "print_search_summary",
    "print_directory_summary",
    "print_download_summary",
    "print_import_summary",
    "print_match_details",
    "print_section_header",
]
