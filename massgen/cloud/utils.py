import base64
import io
import re
import tarfile
from pathlib import Path
from typing import Any

from .modal_app import CONTEXT_MOUNT_PATH, CONTEXT_VOLUME_NAME


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


# ── Modal Volume helpers for context path upload ──


def process_context_paths(
    context_paths: list[dict[str, Any]],
    mount_point: str = CONTEXT_MOUNT_PATH,
    cloud_job_id: str = "",
) -> list[dict[str, Any]]:
    import modal

    vol = modal.Volume.from_name(CONTEXT_VOLUME_NAME, create_if_missing=True)
    rewritten: list[dict[str, Any]] = []

    with vol.batch_upload(force=True) as batch:
        for idx, entry in enumerate(context_paths):
            if isinstance(entry, dict):
                local_path = entry.get("path", "")
                permission = entry.get("permission", "read")
                protected = entry.get("protected_paths", [])
            else:
                local_path = str(entry)
                permission = "read"
                protected = []

            if not local_path:
                continue

            src = Path(local_path)

            if not src.exists():
                raise FileNotFoundError(src)

            remote_root = Path(mount_point) / cloud_job_id / str(idx)

            if src.is_file():
                batch.put_file(str(src), f"{cloud_job_id}/{idx}/{src.name}")
                remote_path = str(remote_root / src.name)
            else:
                batch.put_directory(str(src), f"{cloud_job_id}/{idx}")
                remote_path = str(remote_root)

            entry_out = {"path": remote_path, "permission": permission}

            if protected:
                entry_out["protected_paths"] = protected

            rewritten.append(entry_out)

    return rewritten
