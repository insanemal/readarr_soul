<p align="center">
<img src="https://raw.githubusercontent.com/insanemal/readarr_soul/refs/heads/main/rsoul.png" align="center" width="592" height="691">
</p>
<h1 align="center">R:soul</h1>
<p align="center">
  A Python script that connects Readarr with Soulseek!
</p>

# About

**R:soul** is an automated downloader that bridges **Readarr** (for book management) with **Soulseek** (for peer-to-peer file sharing). It automatically searches for missing books in your Readarr library, finds them on Soulseek via `slskd`, downloads them, and imports them back into Readarr.

This project is a fork of [Soularr](https://github.com/mrusse/soularr) (originally for Lidarr/Music), now fully refactored and adapted for the specific needs of ebooks.

> **Note**: This project is **not** affiliated with Readarr. Please do not contact the Readarr team for support regarding this script.

## Quick Start

1.  **Prerequisites**:
    *   **Readarr**: Installed and running.
    *   **Slskd**: A Soulseek client (installed and running).
    *   **Python 3.10+**: If running from source (or use Docker).

2.  **Configuration**:
    *   Copy `config.ini` to your data directory.
    *   Edit `config.ini` with your API keys and URLs:
        *   **[Readarr]**: Set `api_key` and `host_url`. `download_dir` must match where Slskd saves files *as seen by Readarr*.
        *   **[Slskd]**: Set `api_key` and `host_url`.
    *   Review `[Search Settings]` to tune matching strictness.

3.  **Run**:
    *   **Docker**: `docker-compose up -d`
    *   **Source**: `python rsoul.py`

## Features
- **Automated Search**: Finds missing books in Readarr and searches Soulseek.
- **Smart Matching**: Validates downloads using author/title matching and metadata checks (ISBN, internal metadata).
- **Import Management**: Automatically imports successful downloads into Readarr.
- **Docker Support**: Ready for containerized deployment.

## Status
Active Development. The core functionality is stable, but ongoing refactoring is improving maintainability and error handling.

## Support
Join the Discord: https://discord.gg/mwX4dMSQGH

