#!/usr/bin/env python3
"""Pre-commit hook to ensure package name is 'massgen' in pyproject.toml."""

import re
import sys
from pathlib import Path


def check_package_name():
    """Check that the package name in pyproject.toml is 'massgen'."""
    pyproject_path = Path("pyproject.toml")

    if not pyproject_path.exists():
        print("Error: pyproject.toml not found")
        return 1

    content = pyproject_path.read_text()

    # Look for name = "..." in [project] section
    match = re.search(r'^\[project\].*?^name\s*=\s*"([^"]+)"', content, re.MULTILINE | re.DOTALL)

    if not match:
        print("Error: Could not find package name in pyproject.toml")
        return 1

    package_name = match.group(1)

    if package_name != "massgen":
        print(f"Error: Package name must be 'massgen', found '{package_name}'")
        print("\nThis check prevents accidentally committing test package names.")
        print("If you're testing with TestPyPI, use a temporary name but don't commit it.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(check_package_name())
