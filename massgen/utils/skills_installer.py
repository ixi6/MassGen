# -*- coding: utf-8 -*-
"""Skills installation utility for MassGen.

This module provides cross-platform installation of skills including:
- openskills CLI (npm package)
- Anthropic skills collection
- OpenAI skills collection
- Vercel agent skills collection
- Vercel Agent Browser skill
- Crawl4AI skill

Works on Windows, macOS, and Linux.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Color constants for terminal output
RESET = "\033[0m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_RED = "\033[91m"

OPENSKILLS_PACKAGE_SOURCES = {
    "anthropic": "anthropics/skills",
    "openai": "openai/skills",
    "vercel": "vercel-labs/agent-skills",
    "agent_browser": "vercel-labs/agent-browser",
}

SKILL_PACKAGE_METADATA = {
    "anthropic": {
        "name": "Anthropic Skills Collection",
        "description": "Official Anthropic skills including code analysis, research, and more",
    },
    "openai": {
        "name": "OpenAI Skills Collection",
        "description": "Official OpenAI skill library with curated and experimental skill sets",
    },
    "vercel": {
        "name": "Vercel Agent Skills",
        "description": "Vercel-maintained skill pack for modern full-stack and app workflows",
    },
    "agent_browser": {
        "name": "Vercel Agent Browser Skill",
        "description": "Skill for browser-native automation via the agent-browser runtime",
    },
    "crawl4ai": {
        "name": "Crawl4AI",
        "description": "Web crawling and scraping skill for extracting content from websites",
    },
}

# Marker skills per package. Used to detect installs by scanning .agent/skills/.
ANTHROPIC_MARKER_SKILLS = {
    "algorithmic-art",
    "artifacts-builder",
    "brand-guidelines",
    "canvas-design",
    "internal-comms",
    "mcp-builder",
    "theme-factory",
    "webapp-testing",
}

OPENAI_MARKER_SKILLS = {
    "openai-docs",
    "gh-fix-ci",
    "develop-web-game",
    "sora",
    "imagegen",
    "playwright",
    "screenshot",
    "yeet",
}

VERCEL_MARKER_SKILLS = {
    "react-best-practices",
    "web-design-guidelines",
    "react-native-guidelines",
    "composition-patterns",
    "vercel-deploy-claimable",
}


def _get_package_manifest_path() -> Path:
    """Return metadata file tracking package installations done by MassGen."""
    return Path.home() / ".agent" / "skills" / ".massgen_package_installs.json"


def _load_package_manifest() -> dict[str, Any]:
    """Load package install metadata tracked by MassGen."""
    manifest_path = _get_package_manifest_path()
    if not manifest_path.exists():
        return {}

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def _save_package_manifest(manifest: dict[str, Any]) -> None:
    """Persist package install metadata tracked by MassGen."""
    manifest_path = _get_package_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _record_package_install(package_id: str, source: str) -> None:
    """Record successful package installation for future status checks."""
    manifest = _load_package_manifest()
    manifest[package_id] = {
        "source": source,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_package_manifest(manifest)


def _is_package_recorded(package_id: str) -> bool:
    """Check if a package was previously installed by MassGen."""
    manifest = _load_package_manifest()
    pkg = manifest.get(package_id, {})
    return isinstance(pkg, dict) and bool(pkg.get("source"))


def _print_header(message: str) -> None:
    """Print a formatted header message."""
    print(f"\n{BRIGHT_CYAN}{'═' * 60}{RESET}")
    print(f"{BRIGHT_CYAN}{message:^60}{RESET}")
    print(f"{BRIGHT_CYAN}{'═' * 60}{RESET}\n")


def _print_step(step: str, total: int, message: str) -> None:
    """Print a step indicator."""
    print(f"{BRIGHT_CYAN}[{step}/{total}] {message}{RESET}")


def _print_success(message: str) -> None:
    """Print a success message."""
    print(f"{BRIGHT_GREEN}✓ {message}{RESET}")


def _print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{BRIGHT_YELLOW}⚠ {message}{RESET}")


def _print_error(message: str) -> None:
    """Print an error message."""
    print(f"{BRIGHT_RED}✗ {message}{RESET}")


def _print_info(message: str) -> None:
    """Print an info message."""
    print(f"{BRIGHT_CYAN}  {message}{RESET}")


def _check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(command) is not None


def _run_command(
    command: list[str],
    check: bool = True,
    capture_output: bool = False,
    input_text: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> Optional[subprocess.CompletedProcess]:
    """Run a shell command.

    Args:
        command: Command and arguments as a list
        check: Whether to raise on non-zero exit
        capture_output: Whether to capture stdout/stderr
        input_text: Optional stdin text to send to the process
        env: Optional environment variable overrides

    Returns:
        CompletedProcess if successful, None if failed and check=False
    """
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=True,
            input=input_text,
            env=env,
        )
    except subprocess.CalledProcessError:
        if check:
            raise
        return None


def _get_npm_global_package_version(package: str) -> Optional[str]:
    """Get the version of a globally installed npm package.

    Args:
        package: Package name (e.g., 'openskills')

    Returns:
        Version string if installed, None otherwise
    """
    try:
        result = subprocess.run(
            ["npm", "list", "-g", package, "--depth=0"],
            capture_output=True,
            text=True,
            check=False,
        )
        # npm list returns non-zero if package not found, but still outputs info
        if package in result.stdout:
            # Extract version from output like: openskills@1.2.3
            for line in result.stdout.split("\n"):
                if package in line and "@" in line:
                    return line.split("@")[-1].strip()
        return None
    except Exception:
        return None


def install_openskills_cli() -> bool:
    """Install openskills CLI via npm.

    Returns:
        True if successful, False otherwise
    """
    _print_step("1", "6", "Installing openskills CLI...")

    # Check if npm is available
    if not _check_command_exists("npm"):
        _print_error("npm is not installed")
        _print_info("Please install Node.js and npm first:")
        _print_info("  macOS:   brew install node")
        _print_info("  Linux:   sudo apt-get install nodejs npm")
        _print_info("  Windows: Download from https://nodejs.org/")
        return False

    # Check if openskills already installed
    version = _get_npm_global_package_version("openskills")
    if version:
        _print_warning(f"openskills already installed: {version}")
        return True

    # Install openskills
    _print_info("Installing openskills globally...")
    result = _run_command(["npm", "install", "-g", "openskills"], check=False)

    if result and result.returncode == 0:
        _print_success("openskills installed successfully")
        return True
    else:
        _print_error("Failed to install openskills")
        return False


def install_anthropic_skills() -> bool:
    """Install Anthropic skills collection via openskills.

    Returns:
        True if successful, False otherwise
    """
    _print_step("2", "6", "Installing Anthropic skills collection...")
    return _install_openskills_skill_package("anthropic")


def install_openai_skills() -> bool:
    """Install OpenAI skills collection via openskills.

    Returns:
        True if successful, False otherwise
    """
    _print_step("3", "6", "Installing OpenAI skills collection...")
    return _install_openskills_skill_package("openai")


def install_vercel_skills() -> bool:
    """Install Vercel agent skills collection via openskills.

    Returns:
        True if successful, False otherwise
    """
    _print_step("4", "6", "Installing Vercel agent skills collection...")
    return _install_openskills_skill_package("vercel")


def install_agent_browser_skill() -> bool:
    """Install Vercel Agent Browser skill via openskills.

    Returns:
        True if successful, False otherwise
    """
    _print_step("5", "6", "Installing Vercel Agent Browser skill...")
    return _install_openskills_skill_package("agent_browser")


def _install_openskills_skill_package(package_id: str) -> bool:
    """Install a specific openskills package and record install metadata."""
    if package_id not in OPENSKILLS_PACKAGE_SOURCES:
        _print_error(f"Unknown openskills package: {package_id}")
        return False

    # Check if openskills is available
    if not _check_command_exists("openskills"):
        _print_error("openskills not found")
        _print_info("Run with --setup-skills again to install openskills first")
        return False

    source = OPENSKILLS_PACKAGE_SOURCES[package_id]
    package_name = SKILL_PACKAGE_METADATA[package_id]["name"]

    _print_info(f"Installing/updating from {source}...")
    openskills_env = os.environ.copy()
    openskills_env["CI"] = "1"
    result = _run_command(
        ["openskills", "install", source, "--universal", "-y"],
        check=False,
        capture_output=True,
        # Handle edge-cases where openskills still prompts (e.g. duplicate skill names).
        # Sending newlines makes the command non-blocking in non-interactive flows.
        input_text="\n\n\n\n",
        env=openskills_env,
    )

    if result and result.returncode == 0:
        _record_package_install(package_id, source)
        _print_success(f"{package_name} installed")
        return True

    # openskills may return non-zero after partial success (e.g. duplicate skill prompt path).
    # Treat Agent Browser package as installed if the target skill now exists.
    if package_id == "agent_browser":
        if (Path.home() / ".agent" / "skills" / "agent-browser").exists():
            _record_package_install(package_id, source)
            _print_warning(f"{package_name} appears installed despite non-zero openskills exit")
            return True

    _print_error(f"Failed to install {package_name}")
    if result and (result.stdout or result.stderr):
        tail = "\n".join((result.stdout or "").splitlines()[-8:] + (result.stderr or "").splitlines()[-8:])
        if tail.strip():
            _print_info("openskills output (tail):")
            print(tail)
    return False


def install_crawl4ai_skill() -> bool:
    """Install Crawl4AI skill from docs.crawl4ai.com.

    Returns:
        True if successful, False otherwise
    """
    _print_step("6", "6", "Installing Crawl4AI skill...")

    skills_dir = Path.home() / ".agent" / "skills"
    crawl4ai_dir = skills_dir / "crawl4ai"

    # Check if already installed
    if crawl4ai_dir.exists():
        _print_warning("Crawl4AI skill directory already exists")
        _print_info(f"Skipping download (delete {crawl4ai_dir} to reinstall)")
        return True

    # Download and install
    _print_info("Downloading Crawl4AI skill...")

    url = "https://docs.crawl4ai.com/assets/crawl4ai-skill.zip"

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "crawl4ai-skill.zip"

            # Download
            try:
                urllib.request.urlretrieve(url, zip_path)
            except Exception as e:
                _print_error(f"Failed to download Crawl4AI skill: {e}")
                _print_info(f"URL: {url}")
                _print_info(f"You can download and extract manually to: {crawl4ai_dir}")
                return False

            # Extract
            _print_info(f"Extracting to {crawl4ai_dir}...")

            try:
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    # Extract to temp directory first
                    zip_ref.extractall(temp_path)

                # Move extracted content to final location
                skills_dir.mkdir(parents=True, exist_ok=True)

                # Handle different zip structures
                if (temp_path / "crawl4ai").exists():
                    shutil.move(str(temp_path / "crawl4ai"), str(crawl4ai_dir))
                elif (temp_path / "crawl4ai-skill").exists():
                    shutil.move(str(temp_path / "crawl4ai-skill"), str(crawl4ai_dir))
                else:
                    # If zip extracts to multiple files, create dir and move all
                    crawl4ai_dir.mkdir(parents=True, exist_ok=True)
                    for item in temp_path.iterdir():
                        if item.name != "crawl4ai-skill.zip":
                            dest = crawl4ai_dir / item.name
                            if item.is_dir():
                                shutil.copytree(item, dest)
                            else:
                                shutil.copy2(item, dest)

                _print_success("Crawl4AI skill installed successfully")
                return True

            except Exception as e:
                _print_error(f"Failed to extract Crawl4AI skill: {e}")
                return False

    except Exception as e:
        _print_error(f"Unexpected error: {e}")
        return False


def list_available_skills() -> dict:
    """List all available skills grouped by location.

    Scans for skills in three locations (matching WebUI /api/skills):
    - Built-in: massgen/skills/
    - User: ~/.agent/skills/ (home directory - where openskills installs)
    - Project: .agent/skills/ (current working directory)

    Returns:
        Dict with 'builtin', 'user', and 'project' keys, each containing list of skill dicts.
        Each skill dict has 'name', 'description', and 'location' keys.
    """
    from massgen.filesystem_manager.skills_manager import scan_skills

    all_skills = []
    seen_names = set()

    # Scan user skills (~/.agent/skills/)
    user_dir = Path.home() / ".agent" / "skills"
    user_skills = scan_skills(user_dir)
    for skill in user_skills:
        if skill["location"] == "project":  # scan_skills marks these as "project"
            skill["location"] = "user"  # Re-label as "user" for home directory
        if skill["name"] not in seen_names:
            all_skills.append(skill)
            seen_names.add(skill["name"])

    # Scan project skills (.agent/skills/ in cwd)
    project_dir = Path.cwd() / ".agent" / "skills"
    if project_dir.exists():
        project_skills = scan_skills(project_dir)
        for skill in project_skills:
            if skill["name"] not in seen_names:
                all_skills.append(skill)
                seen_names.add(skill["name"])

    # Builtin skills are already included from scan_skills

    # Group by location
    return {
        "builtin": [s for s in all_skills if s["location"] == "builtin"],
        "user": [s for s in all_skills if s["location"] == "user"],
        "project": [s for s in all_skills if s["location"] == "project"],
    }


def check_skill_packages_installed() -> dict:
    """Check installation status of skill packages.

    Detection is filesystem-based: we scan .agent/skills/ directories (both
    user-level and project-level) and look for marker skills from each package.
    The manifest file is NOT used for detection since it can become stale when
    skills are removed outside of MassGen.

    Returns:
        Dict with package info including installation status.
    """
    skills = list_available_skills()
    # Installed skills = user + project (excluding builtin)
    installed_skills = skills["user"] + skills["project"]
    installed_skill_names = {s["name"].strip().lower() for s in installed_skills}

    # Detect each package by checking for marker skills on disk.
    anthropic_skills = [s for s in installed_skills if s["name"].lower() in ANTHROPIC_MARKER_SKILLS]
    has_anthropic = bool(anthropic_skills)

    openai_skills = [s for s in installed_skills if s["name"].lower() in OPENAI_MARKER_SKILLS]
    has_openai = bool(openai_skills)

    vercel_skills = [s for s in installed_skills if s["name"].lower() in VERCEL_MARKER_SKILLS]
    has_vercel = bool(vercel_skills)

    has_agent_browser = "agent-browser" in installed_skill_names

    has_crawl4ai = any(s["name"].lower().startswith("crawl4ai") for s in installed_skills)

    return {
        "anthropic": {
            "name": SKILL_PACKAGE_METADATA["anthropic"]["name"],
            "description": SKILL_PACKAGE_METADATA["anthropic"]["description"],
            "installed": has_anthropic,
            "skill_count": len(anthropic_skills) if has_anthropic else 0,
        },
        "openai": {
            "name": SKILL_PACKAGE_METADATA["openai"]["name"],
            "description": SKILL_PACKAGE_METADATA["openai"]["description"],
            "installed": has_openai,
        },
        "vercel": {
            "name": SKILL_PACKAGE_METADATA["vercel"]["name"],
            "description": SKILL_PACKAGE_METADATA["vercel"]["description"],
            "installed": has_vercel,
        },
        "agent_browser": {
            "name": SKILL_PACKAGE_METADATA["agent_browser"]["name"],
            "description": SKILL_PACKAGE_METADATA["agent_browser"]["description"],
            "installed": has_agent_browser,
        },
        "crawl4ai": {
            "name": SKILL_PACKAGE_METADATA["crawl4ai"]["name"],
            "description": SKILL_PACKAGE_METADATA["crawl4ai"]["description"],
            "installed": has_crawl4ai,
        },
    }


def display_skills_summary() -> None:
    """Display skills summary in terminal - matches WebUI structure."""
    skills = list_available_skills()
    builtin = skills["builtin"]
    user = skills["user"]
    project = skills["project"]
    packages = check_skill_packages_installed()

    installed_count = len(user) + len(project)
    total = len(builtin) + installed_count

    print(f"\n{BRIGHT_CYAN}{'═' * 60}{RESET}")
    print(f"{BRIGHT_CYAN}{'Skills':^60}{RESET}")
    print(f"{BRIGHT_CYAN}{'═' * 60}{RESET}\n")

    # Summary
    print(f"{BRIGHT_GREEN}{total} Skill(s) Available{RESET}")
    print(f"  {len(builtin)} built-in, {installed_count} installed\n")

    # Skill Packages section (matches WebUI)
    print(f"{BRIGHT_CYAN}Skill Packages:{RESET}")
    print(f"{BRIGHT_YELLOW}Install skill packages to add new capabilities.{RESET}\n")

    for pkg_id, pkg in packages.items():
        if pkg["installed"]:
            count_info = f" ({pkg['skill_count']} skills)" if pkg.get("skill_count") else ""
            print(f"  {BRIGHT_GREEN}✓{RESET} {pkg['name']} [installed{count_info}]")
        else:
            print(f"  {BRIGHT_RED}✗{RESET} {pkg['name']} [not installed]")
        print(f"      {pkg['description']}")

    print()


def install_skills() -> None:
    """Main entry point for skills installation.

    Installs:
    1. openskills CLI (npm package)
    2. Anthropic skills collection
    3. OpenAI skills collection
    4. Vercel agent skills collection
    5. Vercel Agent Browser skill
    6. Crawl4AI skill

    This function is called by `massgen --setup-skills` command.
    """
    _print_header("MassGen Skills Installation")

    print(f"{BRIGHT_CYAN}Platform: {platform.system()}{RESET}\n")

    # Track success
    results = []

    # 1. Install openskills CLI
    results.append(("openskills CLI", install_openskills_cli()))
    print()

    # 2-5. Install openskills-backed packages (only if openskills succeeded)
    if results[0][1]:
        results.append(("Anthropic skills", install_anthropic_skills()))
        print()
        results.append(("OpenAI skills", install_openai_skills()))
        print()
        results.append(("Vercel agent skills", install_vercel_skills()))
        print()
        results.append(("Vercel Agent Browser skill", install_agent_browser_skill()))
    else:
        _print_warning("Skipping openskills packages (openskills CLI required)")
        results.append(("Anthropic skills", False))
        results.append(("OpenAI skills", False))
        results.append(("Vercel agent skills", False))
        results.append(("Vercel Agent Browser skill", False))
    print()

    # 6. Install Crawl4AI skill
    results.append(("Crawl4AI skill", install_crawl4ai_skill()))
    print()

    # Summary
    _print_header("Installation Summary")

    all_success = all(success for _, success in results)

    for component, success in results:
        if success:
            _print_success(f"{component}")
        else:
            _print_error(f"{component}")

    print()

    if all_success:
        _print_success("All skills installed successfully!")
        print()

        # Show skills directory
        skills_dir = Path.home() / ".agent" / "skills"
        if skills_dir.exists():
            skill_count = len(list(skills_dir.iterdir()))
            print(f"{BRIGHT_CYAN}Total skills available: {skill_count}{RESET}")
            print(f"{BRIGHT_CYAN}Skills directory: {skills_dir}{RESET}")
            print()

        print(f"{BRIGHT_CYAN}Next steps:{RESET}")
        print("  • Skills are now available in Claude Code and Gemini CLI")
        print("  • Run 'massgen' to start using MassGen with skills")
        print("  • See documentation: https://docs.massgen.ai")
        print()
    else:
        _print_warning("Some installations failed - see errors above")
        print()
        print(f"{BRIGHT_CYAN}Troubleshooting:{RESET}")
        print("  • Ensure Node.js and npm are installed")
        print("  • Check your internet connection")
        print("  • Run 'massgen --setup-skills' again to retry")
        print()
        sys.exit(1)


def install_quickstart_skills() -> bool:
    """Ensure quickstart-required skill packages are installed.

    This is used by ``massgen --quickstart``. Unlike ``install_skills()``,
    this function never exits the process and only installs missing packages.

    Returns:
        True if required skill packages are available after installation attempts,
        False otherwise.
    """
    _print_header("Quickstart Skills Setup")

    packages = check_skill_packages_installed()
    openskills_installed = _check_command_exists("openskills")
    anthropic_installed = packages["anthropic"]["installed"]
    openai_installed = packages["openai"]["installed"]
    vercel_installed = packages["vercel"]["installed"]
    agent_browser_installed = packages["agent_browser"]["installed"]
    crawl4ai_installed = packages["crawl4ai"]["installed"]

    if openskills_installed and anthropic_installed and openai_installed and vercel_installed and agent_browser_installed and crawl4ai_installed:
        _print_success("Required quickstart skill packages are already installed")
        return True

    results = []

    # Ensure openskills CLI is available for skill reads.
    if openskills_installed:
        _print_success("openskills CLI already installed")
        results.append(("openskills CLI", True))
    else:
        results.append(("openskills CLI", install_openskills_cli()))

    openskills_ok = results[-1][1]

    # Install Anthropic collection only when missing.
    if anthropic_installed:
        _print_success("Anthropic skills already installed")
        results.append(("Anthropic skills", True))
    else:
        if openskills_ok:
            results.append(("Anthropic skills", install_anthropic_skills()))
        else:
            _print_warning("Skipping Anthropic skills because openskills failed to install")
            results.append(("Anthropic skills", False))

    # Install OpenAI collection only when missing.
    if openai_installed:
        _print_success("OpenAI skills already installed")
        results.append(("OpenAI skills", True))
    else:
        if openskills_ok:
            results.append(("OpenAI skills", install_openai_skills()))
        else:
            _print_warning("Skipping OpenAI skills because openskills failed to install")
            results.append(("OpenAI skills", False))

    # Install Vercel agent skills collection only when missing.
    if vercel_installed:
        _print_success("Vercel agent skills already installed")
        results.append(("Vercel agent skills", True))
    else:
        if openskills_ok:
            results.append(("Vercel agent skills", install_vercel_skills()))
        else:
            _print_warning("Skipping Vercel agent skills because openskills failed to install")
            results.append(("Vercel agent skills", False))

    # Install Vercel Agent Browser skill only when missing.
    if agent_browser_installed:
        _print_success("Vercel Agent Browser skill already installed")
        results.append(("Vercel Agent Browser skill", True))
    else:
        if openskills_ok:
            results.append(("Vercel Agent Browser skill", install_agent_browser_skill()))
        else:
            _print_warning("Skipping Vercel Agent Browser skill because openskills failed to install")
            results.append(("Vercel Agent Browser skill", False))

    # Install Crawl4AI only when missing.
    if crawl4ai_installed:
        _print_success("Crawl4AI skill already installed")
        results.append(("Crawl4AI skill", True))
    else:
        results.append(("Crawl4AI skill", install_crawl4ai_skill()))

    all_success = all(success for _, success in results)
    if all_success:
        _print_success("Quickstart skills are ready")
    else:
        _print_warning("Quickstart will continue, but some skill packages failed to install")
        _print_info("Run 'massgen --setup-skills' to retry skill installation")

    return all_success


if __name__ == "__main__":
    # Allow running directly for testing
    install_skills()
