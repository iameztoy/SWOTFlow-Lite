"""Validated, opt-in settings. Browser upload remains the default."""
from dataclasses import dataclass
import re

BACKENDS = {"Browser (existing uploader)": "browser", "Google Cloud Storage": "gcs"}

def project_id_error(project: str, bucket: str = "") -> str:
    """Return an actionable message before a Cloud client uses the project ID."""
    if re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
        return ""
    if project and ("://" in project or "/" in project or project == bucket or "_" in project or "." in project):
        return ("The Google Cloud project ID looks like a bucket or path. Enter the project ID "
                "shown in Google Cloud Console (for example, hardy-tenure-383607). "
                "Enter the bucket name in Bucket name (for example, swot_hr100m), without gs://.")
    return "Enter the Google Cloud project ID from Cloud Console (for example, hardy-tenure-383607)."


@dataclass(frozen=True)
class CloudConfig:
    project: str = ""
    bucket: str = ""
    prefix: str = "swotflow-staging"
    staging_limit_gib: float = 50.0
    delete_after_verification: bool = True
    chunk_mib: int = 16
    concurrent_uploads: int = 1

    @classmethod
    def from_dict(cls, data):
        values = data or {}
        return cls(str(values.get("project", "")).strip(), str(values.get("bucket", "")).strip(),
                   str(values.get("prefix", "swotflow-staging")).strip().strip("/"),
                   float(values.get("staging_limit_gib", 50)), bool(values.get("delete_after_verification", True)),
                   int(values.get("chunk_mib", 16)), int(values.get("concurrent_uploads", 1)))

    def validate(self):
        project_error = project_id_error(self.project, self.bucket)
        if project_error:
            raise ValueError(project_error)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", self.bucket):
            raise ValueError("Cloud Upload: enter a bucket name without gs:// or a folder path.")
        if not self.prefix or not re.fullmatch(r"[A-Za-z0-9/_-]+", self.prefix) or ".." in self.prefix:
            raise ValueError("Cloud Upload: use a dedicated, nonempty staging prefix.")
        if not 0 < self.staging_limit_gib <= 100000:
            raise ValueError("Cloud Upload: staged storage limit must be positive (GiB).")
        if not 1 <= self.chunk_mib <= 128:
            raise ValueError("Cloud Upload: chunk size must be between 1 and 128 MiB.")
        if not 1 <= self.concurrent_uploads <= 16:
            raise ValueError("Cloud Upload: concurrent transfers must be between 1 and 16.")
