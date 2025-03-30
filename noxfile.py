from __future__ import annotations

import os

import nox
from nox.sessions import Session


@nox.session(reuse_venv=True)
def format(session: Session) -> None:
    """Run automatic code formatters"""
    session.run("poetry", "install", external=True)
    session.run("black", ".")
    session.run("isort", ".")
    session.run("autoflake", "--in-place", ".")


@nox.session(reuse_venv=True)
def tests(session: Session) -> None:
    """Run the complete test suite"""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        session.notify("test_types")
        session.notify("test_style")
        session.notify("test_suite")
    else:
        session.notify("docker_test")


@nox.session(reuse_venv=True)
def docker_test(session: Session) -> None:
    """Run the complete test suite"""
    session.notify("test_create_containers")
    session.notify("test_types")
    session.notify("test_style")
    session.notify("test_suite")
    session.notify("test_cleanup_containers")


@nox.session(reuse_venv=True)
def test_create_containers(session: Session) -> None:
    session.run(
        "sudo",
        "docker",
        "compose",
        "-f",
        ".devcontainer/docker-compose.yml",
        "pull",
        external=True,
    )
    session.run(
        "sudo",
        "docker",
        "compose",
        "-f",
        ".devcontainer/docker-compose.yml",
        "up",
        "-d",
        external=True,
    )


@nox.session(reuse_venv=True)
def test_cleanup_containers(session: Session) -> None:
    session.run(
        "sudo",
        "docker",
        "compose",
        "-f",
        ".devcontainer/docker-compose.yml",
        "down",
        external=True,
    )
    session.run("git", "checkout", "--", "tests/docker_configs/", external=True)


@nox.session(reuse_venv=True)
def test_suite(session: Session) -> None:
    """Run the Python-based test suite"""
    session.run("poetry", "install", external=True)
    session.run(
        "pytest",
        "--showlocals",
        "--reruns",
        "3",
        "--reruns-delay",
        "5",
        "--cov=pyarr",
        "--cov-report",
        "xml",
        "--cov-report",
        "term-missing",
        "-vv",
    )


@nox.session(reuse_venv=True)
def test_types(session: Session) -> None:
    """Check that typing is working as expected"""
    session.run("poetry", "install", external=True)
    session.run("mypy", "--show-error-codes", "pyarr")


@nox.session(reuse_venv=True)
def test_style(session: Session) -> None:
    """Check that style guidelines are being followed"""
    session.run("poetry", "install", external=True)
    session.run("flake8", "pyarr", "tests")
    session.run(
        "black",
        "pyarr",
        "--check",
    )
    session.run("isort", "pyarr", "--check-only")
    session.run("autoflake", "-r", "pyarr")
    session.run("interrogate", "pyarr")


@nox.session(reuse_venv=True)
def serve_docs(session: Session) -> None:
    """Create local copy of docs for testing"""
    session.run("poetry", "install", external=True)
    session.run("sphinx-autobuild", "docs", "build")


@nox.session(reuse_venv=True)
def build_docs(session: Session) -> None:
    """Create local copy of docs for testing"""
    session.run("poetry", "install", external=True)
    session.run("sphinx-build", "-b", "html", "docs", "build")


@nox.session(reuse_venv=True)
def install_release(session: Session) -> None:
    session.run("npm", "install", "@semantic-release/changelog")
    session.run("npm", "install", "@semantic-release/exec")
    session.run("npm", "install", "@semantic-release/git")
    session.run("npm", "install", "@semantic-release/github")
    session.run("npm", "install", "conventional-changelog-conventionalcommits@7.0.2")
    session.run("npm", "install", "semantic-release-pypi")


@nox.session(reuse_venv=True)
def release(session: Session) -> None:
    """Release a new version of the package"""
    pypi_password = session.posargs[0]
    session.run("poetry", "install", external=True)
    session.notify("install_release")
    session.run("npx", "semantic-release", "--debug")
    session.run("poetry", "build", external=True)
    session.run(
        "poetry", "publish", "-u", "__token__", "-p", pypi_password, external=True
    )
