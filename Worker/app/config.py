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
    # When concurrency > 1, assign different tune params to each parallel lane (faster).
    param_split_concurrency: bool = True
    # Max trials after base benchmark for random / optuna search.
    adaptive_max_trials: int = 30
    # Center-crop job window for faster trials (0 = use full round window).
    benchmark_subwindow_mb: int = 2
    # Fixed Docker/GATK resources per concurrent trial slot.
    trial_threads: int = 4
    trial_memory_gb: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
