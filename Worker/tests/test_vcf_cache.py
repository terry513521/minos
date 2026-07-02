import json
from pathlib import Path

from app.conf_hash import conf_cache_key, conf_for_cache
from app.vcf_cache import VcfCache
from app.config import Settings


def test_conf_cache_key_ignores_runtime_keys():
    conf_a = {"gatk_options": {"x": 1}, "threads": 4, "persistent_container": True}
    conf_b = {"gatk_options": {"x": 1}, "threads": 8}
    key_a = conf_cache_key(window="chr21:1-100", tool="gatk", bam_path="/bam.bam", conf=conf_a)
    key_b = conf_cache_key(window="chr21:1-100", tool="gatk", bam_path="/bam.bam", conf=conf_b)
    assert key_a == key_b
    assert "threads" not in conf_for_cache(conf_a)


def test_vcf_cache_roundtrip(tmp_path):
    settings = Settings(
        data_dir=str(tmp_path),
        vcf_cache_enabled=True,
        vcf_cache_dir="cache",
    )
    cache = VcfCache(settings)
    source = tmp_path / "query.vcf.gz"
    source.write_bytes(b"vcf")

    cache.store(
        window="chr21:1-100",
        tool="gatk",
        bam_path="/data/HG002.bam",
        conf={"gatk_options": {"min_mapping_quality_score": 20}},
        source_vcf=source,
        score=0.42,
        raw_score=42.0,
        variant_count=99,
    )

    hit = cache.lookup(
        window="chr21:1-100",
        tool="gatk",
        bam_path="/data/HG002.bam",
        conf={"gatk_options": {"min_mapping_quality_score": 20}},
    )
    assert hit is not None
    assert hit.score == 0.42
    assert hit.vcf_path.exists()
    meta = json.loads((hit.vcf_path.parent / "meta.json").read_text())
    assert meta["variant_count"] == 99
