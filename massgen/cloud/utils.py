# -*- coding: utf-8 -*-
import base64
import io
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, List


def parse_automation_value(label: str, stderr_text: str) -> str | None:
    """
    Extract the value appearing after a labeled line in multiline text.
    
    Parameters:
    	label (str): Label to match at the start of a line (the function looks for "label: value").
    	stderr_text (str): Multiline text to search for the labeled line.
    
    Returns:
    	str: The captured value with surrounding whitespace removed if a matching line is found, `None` otherwise.
    """
    pattern = re.compile(rf"^{re.escape(label)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(stderr_text)
    return match.group(1).strip() if match else None


def make_tar_gz_b64(source_dir: Path) -> str:
    """
    Create a gzip-compressed tar archive of all files under the given directory and return it encoded as a base64 string.
    
    Parameters:
        source_dir (Path): Directory whose files will be added to the archive; files are included recursively and stored with paths relative to `source_dir`.
    
    Returns:
        str: Base64-encoded string of the resulting tar.gz archive.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in source_dir.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(source_dir)))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def extract_artifacts(tar_b64: str, out_dir: Path) -> None:
    """
    Decode a base64-encoded tar.gz archive and extract its contents into the given output directory.
    
    Parameters:
    	tar_b64 (str): Base64-encoded string containing a gzipped tar archive.
    	out_dir (Path): Destination directory where archive contents will be extracted.
    """
    data = base64.b64decode(tar_b64.encode("utf-8"))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        tf.extractall(out_dir)


# ── Modal Volume helpers for context path upload ──

CONTEXT_VOLUME_NAME = "massgen-context"
CONTEXT_MOUNT_PATH = "/context"


def process_context_paths(
    context_paths: List[Dict[str, Any]],
    mount_point: str = CONTEXT_MOUNT_PATH,
    cloud_job_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Rewrite a list of local context paths into remote volume paths and upload them to the Modal volume.
    
    Each input entry may be a dict with keys `"path"`, `"permission"`, and optional `"protected_paths"`, or a string path. Entries are uploaded in a batch to the volume named by CONTEXT_VOLUME_NAME and placed under {mount_point}/{cloud_job_id}/{index}. For files the returned `"path"` points to the file name under that directory; for directories it points to the directory root. The `"permission"` is preserved and `"protected_paths"` is propagated when present.
    
    Parameters:
        context_paths (List[Dict[str, Any]]): List of context entries to upload. Each entry is either
            a dict with keys `"path"` (str), optional `"permission"` (str, default "read"),
            and optional `"protected_paths"` (List[str]), or a string path.
        mount_point (str): Root mount path inside the volume where contexts are stored.
        cloud_job_id (str): Identifier used as a top-level subdirectory for uploaded entries.
    
    Returns:
        List[Dict[str, Any]]: A list of rewritten entries where each dict contains `"path"` (remote path)
        and `"permission"`, and includes `"protected_paths"` when provided.
    
    Raises:
        FileNotFoundError: If any specified local path does not exist.
    """
    import modal

    vol = modal.Volume.from_name(CONTEXT_VOLUME_NAME, create_if_missing=True)
    rewritten: List[Dict[str, Any]] = []

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
