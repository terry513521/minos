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
    chromosomes: str = "chr20,chr21,chr22"
    platform_url: str = "https://api.theminos.ai"
    reference_url: str = "https://api.theminos.ai/reference"
    # Max trials after base benchmark for adaptive search (optuna, gp, random, sobol, lhs).
    adaptive_max_trials: int = 44
    # Benchmark window size in Mb inside dispatched round (5 = full 5M round; 0 = entire dispatch).
    benchmark_subwindow_mb: int = 5
    # Fixed Docker resources per concurrent trial slot (DeepVariant needs >=16 GB).
    trial_threads: int = 4
    trial_memory_gb: int = 16


@lru_cache
def get_settings() -> Settings:
    return Settings()
