import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_latency  # noqa: E402


def test_aggregate_median_and_mean():
    records = [
        {"rag_ms": 100.0, "ttft_ms": 200.0, "gen_ms": 400.0, "e2e_ms": 500.0},
        {"rag_ms": 200.0, "ttft_ms": 400.0, "gen_ms": 600.0, "e2e_ms": 800.0},
        {"rag_ms": 300.0, "ttft_ms": 600.0, "gen_ms": 800.0, "e2e_ms": 1100.0},
    ]
    agg = bench_latency._aggregate(records)
    assert agg["rag_ms"]["median"] == 200.0
    assert agg["rag_ms"]["mean"] == 200.0
    assert agg["gen_ms"]["median"] == 600.0
    assert agg["e2e_ms"]["mean"] == 800.0


def test_aggregate_empty_is_zero():
    agg = bench_latency._aggregate([])
    for phase in ("rag_ms", "ttft_ms", "gen_ms", "e2e_ms"):
        assert agg[phase]["median"] == 0.0
        assert agg[phase]["mean"] == 0.0


def test_aggregate_skips_none_values():
    # --no-llm: ttft_ms/gen_ms/e2e_ms sind None und dürfen nicht als 0 zählen
    records = [
        {"rag_ms": 100.0, "ttft_ms": None, "gen_ms": None, "e2e_ms": 100.0},
        {"rag_ms": 300.0, "ttft_ms": None, "gen_ms": None, "e2e_ms": 300.0},
    ]
    agg = bench_latency._aggregate(records)
    assert agg["rag_ms"]["median"] == 200.0
    # Keine echten ttft-Werte → 0.0 (nicht durch None-Division crashen)
    assert agg["ttft_ms"]["median"] == 0.0
    assert agg["ttft_ms"]["mean"] == 0.0
