#!/usr/bin/env python3
"""
Validate all configuration files in the repository.

This script validates all YAML config files in the massgen/configs directory
and reports any errors or warnings found.

Usage:
    python scripts/validate_all_configs.py
    python scripts/validate_all_configs.py --strict  # Treat warnings as errors
    python scripts/validate_all_configs.py --verbose # Show details for all configs
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from massgen.config_validator import ConfigValidator  # noqa: E402


def main():
    """Validate all configs in the repository."""
    parser = argparse.ArgumentParser(description="Validate all MassGen configuration files")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show details for all configs (not just failures)",
    )
    parser.add_argument(
        "--directory",
        type=str,
        default="massgen/configs",
        help="Directory to search for configs (default: massgen/configs)",
    )
    args = parser.parse_args()

    # Find all YAML config files
    configs_dir = Path(args.directory)
    if not configs_dir.exists():
        print(f"❌ Directory not found: {configs_dir}")
        sys.exit(1)

    # Data-only YAML files that are not MassGen agent configs
    EXCLUDED_FILES = {"rate_limits.yaml"}

    config_files = sorted(configs_dir.rglob("*.yaml")) + sorted(configs_dir.rglob("*.yml"))
    config_files = [f for f in config_files if f.name not in EXCLUDED_FILES]

    if not config_files:
        print(f"❌ No config files found in {configs_dir}")
        sys.exit(1)

    print(f"🔍 Found {len(config_files)} config files in {configs_dir}\n")

    # Validate each config
    validator = ConfigValidator()
    results = {
        "valid": [],
        "warnings": [],
        "errors": [],
    }

    for config_file in config_files:
        # Get relative path for display
        try:
            rel_path = config_file.relative_to(Path.cwd())
        except ValueError:
            # If not relative to cwd, use relative to configs_dir
            rel_path = config_file.relative_to(configs_dir.parent)

        result = validator.validate_config_file(str(config_file))

        if result.has_errors():
            results["errors"].append((rel_path, result))
            print(f"❌ {rel_path}")
            if args.verbose:
                print(result.format_errors())
                print()
        elif result.has_warnings():
            results["warnings"].append((rel_path, result))
            if args.strict:
                print(f"❌ {rel_path} (warnings in strict mode)")
            else:
                print(f"⚠️  {rel_path}")
            if args.verbose:
                print(result.format_warnings())
                print()
        else:
            results["valid"].append((rel_path, result))
            if args.verbose:
                print(f"✅ {rel_path}")

    # Print summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"✅ Valid configs:     {len(results['valid'])}")
    print(f"⚠️  Configs with warnings: {len(results['warnings'])}")
    print(f"❌ Configs with errors:   {len(results['errors'])}")
    print(f"📊 Total configs:     {len(config_files)}")
    print("=" * 80)

    # Show details for failures
    if results["errors"]:
        print("\n❌ CONFIGS WITH ERRORS:")
        print("-" * 80)
        for config_path, result in results["errors"]:
            print(f"\n{config_path}:")
            print(result.format_errors())

    if results["warnings"] and (args.strict or args.verbose):
        print("\n⚠️  CONFIGS WITH WARNINGS:")
        print("-" * 80)
        for config_path, result in results["warnings"]:
            print(f"\n{config_path}:")
            print(result.format_warnings())

    # Exit with appropriate code
    if results["errors"]:
        sys.exit(1)
    elif args.strict and results["warnings"]:
        sys.exit(1)
    else:
        print("\n✅ All configs validated successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
