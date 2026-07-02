from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GATK_IMAGE = "broadinstitute/gatk:4.5.0.0"


class GatkContainerSlot:
    def __init__(
        self,
        *,
        name: str,
        bam_parent: Path,
        reference_parent: Path,
        output_parent: Path,
        threads: int,
        memory_gb: int,
    ) -> None:
        self.name = name
        self._bam_parent = bam_parent
        self._reference_parent = reference_parent
        self._output_parent = output_parent
        self._threads = threads
        self._memory_gb = memory_gb
        self._lock = threading.Lock()
        self._started = False

    def _docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            if not self._docker_available():
                raise RuntimeError("Docker not found")

            if self._container_running():
                self._started = True
                return

            self._output_parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "docker",
                "run",
                "-d",
                "--name",
                self.name,
                f"--cpus={self._threads}",
                f"--memory={self._memory_gb}g",
                "-v",
                f"{self._bam_parent}:/data/bams:ro",
                "-v",
                f"{self._reference_parent}:/data/reference:ro",
                "-v",
                f"{self._output_parent}:/data/output",
                GATK_IMAGE,
                "sleep",
                "infinity",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "failed to start container")[-500:]
                raise RuntimeError(f"Failed to start GATK container {self.name}: {stderr}")
            self._started = True
            logger.info("Started persistent GATK container %s", self.name)

    def _container_running(self) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", self.name],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def stop(self) -> None:
        with self._lock:
            if not self._started and not self._container_running():
                return
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, check=False)
            self._started = False
            logger.info("Stopped persistent GATK container %s", self.name)

    def run_haplotype_caller(
        self,
        *,
        bam_path: Path,
        reference_path: Path,
        output_vcf_path: Path,
        region: str,
        flags: list[Any],
        timeout: int,
    ) -> dict[str, Any]:
        from templates._common import count_variants

        self.ensure_started()
        output_vcf_path = Path(output_vcf_path).resolve()
        output_vcf_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "docker",
            "exec",
            self.name,
            "gatk",
            "--java-options",
            f"-Xmx{self._memory_gb}g",
            "HaplotypeCaller",
            "-R",
            f"/data/reference/{reference_path.name}",
            "-I",
            f"/data/bams/{bam_path.name}",
            "-O",
            f"/data/output/{output_vcf_path.relative_to(self._output_parent)}",
            "--native-pair-hmm-threads",
            str(self._threads),
            "-L",
            region,
        ]
        for flag in flags:
            cmd.extend(str(flag).split())

        start_time = time.time()
        with self._lock:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                return {"success": False, "variant_count": 0, "error": f"Timeout after {timeout}s"}

        elapsed = time.time() - start_time
        if result.returncode != 0:
            error = result.stderr[-500:] if result.stderr else "GATK failed"
            return {"success": False, "variant_count": 0, "error": error}

        if not output_vcf_path.exists():
            return {"success": False, "variant_count": 0, "error": "VCF not created"}

        return {
            "success": True,
            "variant_count": count_variants(output_vcf_path),
            "metadata": {
                "tool": "GATK",
                "version": "4.5.0.0",
                "runtime_seconds": elapsed,
                "persistent_container": self.name,
            },
        }


class GatkContainerPool:
    def __init__(
        self,
        *,
        job_id: str,
        bam_path: Path,
        reference_path: Path,
        output_parent: Path,
        slots: int,
        threads: int,
        memory_gb: int,
    ) -> None:
        safe_job = "".join(ch if ch.isalnum() else "-" for ch in job_id)[:24]
        self._slots = [
            GatkContainerSlot(
                name=f"minos-gatk-{safe_job}-{index}",
                bam_parent=bam_path.parent.resolve(),
                reference_parent=reference_path.parent.resolve(),
                output_parent=output_parent.resolve(),
                threads=threads,
                memory_gb=memory_gb,
            )
            for index in range(max(1, slots))
        ]
        self._round_robin = 0
        self._assign_lock = threading.Lock()

    def acquire_slot(self) -> GatkContainerSlot:
        with self._assign_lock:
            slot = self._slots[self._round_robin % len(self._slots)]
            self._round_robin += 1
            return slot

    def run_haplotype_caller(self, **kwargs: Any) -> dict[str, Any]:
        slot = self.acquire_slot()
        return slot.run_haplotype_caller(**kwargs)

    def stop_all(self) -> None:
        for slot in self._slots:
            slot.stop()
