# -*- coding: utf-8 -*-
import base64
import io
import re
import tarfile
from pathlib import Path


def parse_automation_value(label: str, stderr_text: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(label)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(stderr_text)
    return match.group(1).strip() if match else None


def make_tar_gz_b64(source_dir: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in source_dir.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(source_dir)))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def extract_artifacts(tar_b64: str, out_dir: Path) -> None:
    data = base64.b64decode(tar_b64.encode("utf-8"))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(out_dir)
