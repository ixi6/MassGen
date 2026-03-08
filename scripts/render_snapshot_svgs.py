#!/usr/bin/env python
"""Render Textual snapshot SVGs to PNG using Playwright's browser engine.

This is intended for local visual review when your tooling cannot display SVG
files directly (for example, some chat/image viewers).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_INPUT_DIR = Path("massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold")
DEFAULT_OUTPUT_DIR = Path("/tmp/massgen_snapshot_pngs")
DEFAULT_DEVICE = "Desktop Chrome"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-render snapshot SVGs into PNGs using Playwright.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing SVG snapshots (default: {DEFAULT_INPUT_DIR}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for rendered PNGs (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"Playwright device preset (default: {DEFAULT_DEVICE}).",
    )
    parser.add_argument(
        "--real-tui-only",
        action="store_true",
        help="Render only snapshots with '_real_tui_' in the filename.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first rendering failure.",
    )
    return parser.parse_args(argv)


def discover_svgs(input_dir: Path, real_tui_only: bool = False) -> list[Path]:
    candidates = sorted(input_dir.glob("*.svg"))
    if real_tui_only:
        return [path for path in candidates if "_real_tui_" in path.name]
    return candidates


def render_svg(svg_path: Path, output_dir: Path, device: str) -> tuple[int, str]:
    png_path = output_dir / f"{svg_path.stem}.png"
    cmd = [
        "npx",
        "playwright",
        "screenshot",
        f"--device={device}",
        svg_path.resolve().as_uri(),
        str(png_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    input_dir = args.input_dir
    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    svg_paths = discover_svgs(input_dir, real_tui_only=args.real_tui_only)
    if not svg_paths:
        selector = "real_tui snapshots" if args.real_tui_only else "SVG snapshots"
        print(f"No {selector} found in: {input_dir}", file=sys.stderr)
        return 1

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Rendering {len(svg_paths)} snapshot(s) to {output_dir}")
    failures = 0

    for svg_path in svg_paths:
        rc, output = render_svg(svg_path, output_dir, args.device)
        if rc == 0:
            print(f"OK  {svg_path.name}")
            continue

        failures += 1
        print(f"FAIL {svg_path.name}", file=sys.stderr)
        if output:
            print(output, file=sys.stderr)
        if args.fail_fast:
            return 1

    if failures:
        print(f"Completed with {failures} failure(s).", file=sys.stderr)
        return 1

    print("All snapshots rendered successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
