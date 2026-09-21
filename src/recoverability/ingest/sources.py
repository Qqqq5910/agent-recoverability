"""Coordinates of the public artifacts this project ingests.

One definition, imported by every ingestion script, so a provenance field cannot
drift between the manifest and an analysis artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["MINI_SWE_AGENT_V1", "PublicSubmission"]


@dataclass(frozen=True, slots=True)
class PublicSubmission:
    """An immutable reference to one public agent submission."""

    source_id: str
    submission: str
    bucket: str
    experiments_repo: str
    agent_name: str
    model_name: str
    benchmark_split: str
    license_status: str
    trajectory_format: str

    @property
    def traj_prefix(self) -> str:
        return f"bash-only/{self.submission}/trajs"

    @property
    def verdict_url(self) -> str:
        return (
            "https://raw.githubusercontent.com/SWE-bench/experiments/main/"
            f"evaluation/verified/{self.submission}/per_instance_details.json"
        )

    def s3_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"


#: The Phase 1A/1B source. ``license_status`` stays "unverified": the
#: submissions bucket is publicly readable, but it carries no explicit data
#: license for third-party trajectories, and this project does not guess. No
#: byte fetched from it is redistributed here.
MINI_SWE_AGENT_V1: Final = PublicSubmission(
    source_id="mini_swe_agent_v1_swebench_verified",
    submission="20250726_mini-v1.0.0_claude-sonnet-4-20250514",
    bucket="swe-bench-submissions",
    experiments_repo="https://github.com/SWE-bench/experiments",
    agent_name="mini-SWE-agent",
    model_name="claude-4-sonnet-20250514",
    benchmark_split="SWE-bench_Verified",
    license_status="unverified",
    trajectory_format="mini-swe-agent traj.json (messages + info)",
)
