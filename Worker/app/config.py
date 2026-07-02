from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="WORKER_",
    )

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"
    name: str = "optimizer-1"
    data_dir: str = "datasets"
    chromosomes: str = "chr20,chr21"
    platform_url: str = "https://api.theminos.ai"
    reference_url: str = "https://api.theminos.ai/reference"
    # Max trials after base benchmark for adaptive search algorithms.
    adaptive_max_trials: int = 30
    # Random N Mb slice inside dispatched window for faster trials (0 = full window).
    benchmark_subwindow_mb: int = 3
    # Fixed Docker/GATK resources per concurrent trial slot.
    trial_threads: int = 4
    trial_memory_gb: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
