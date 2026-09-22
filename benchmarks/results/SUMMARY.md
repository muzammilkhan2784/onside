# Benchmarks

Measured 2026-09-20 on the machine named in the README.

## analytics

```json
{
  "question": "Every shot from outside the box in La Liga, grouped by player",
  "archive": {
    "competition": "La Liga",
    "matches": 867,
    "events": 3132716
  },
  "duckdb_ms": 782.8,
  "duckdb_rows": 5000,
  "duckdb_full_scan_ms": 108.3,
  "dynamodb_sample": {
    "matches": 10,
    "events": 31703,
    "ms": 14092.8
  },
  "dynamodb_projected_ms": 1392574.7,
  "speedup": 1779,
  "note": "The DynamoDB figure is measured over a sample and projected to the full competition, because storing 1.8M event items to answer one analytical question is the thing the split architecture exists to avoid. DynamoDB Local runs in Docker here; managed DynamoDB is faster per request but the shape of the result does not change."
}
```

## correction

```json
{
  "match": "Argentina v France",
  "events": 4407,
  "rebuild_state_ms": {
    "p50": 8.9,
    "p95": 26.6,
    "p99": 26.6,
    "max": 26.6
  },
  "recompute_win_probability_ms": {
    "p50": 6.8,
    "p95": 12.8,
    "p99": 12.8,
    "max": 12.8
  },
  "regenerate_report_ms": {
    "p50": 34.7,
    "p95": 62.1,
    "p99": 62.1,
    "max": 62.1
  },
  "rebuild_whole_document_ms": {
    "p50": 80.5,
    "p95": 95.0,
    "p99": 95.0,
    "max": 95.0
  },
  "full_propagation_p95_ms": 95.0,
  "note": "A correction rebuilds the document from the log rather than patching state: state, features, model, metrics, report and shot map together."
}
```

## correction_propagation

```json
{
  "match": "Argentina v France",
  "events": 4407,
  "rebuild_match_state_from_log_ms": {
    "p50": 7.55,
    "p95": 9.42,
    "max": 15.45
  },
  "recompute_win_probability_series_ms": {
    "p50": 6.5,
    "p95": 7.99,
    "max": 8.58
  },
  "regenerate_report_ms": {
    "p50": 15.92,
    "p95": 19.26,
    "max": 46.33
  },
  "full_propagation_p95_ms": 36.67
}
```

## ingest

```json
{
  "match": "Argentina v France",
  "events": 4407,
  "batch_size": 200,
  "batches": 23,
  "wall_seconds": 81.44,
  "events_per_second_end_to_end": 54,
  "events_per_second_projection_only": 463,
  "per_batch_ms": {
    "produce_to_stream": {
      "p50": 210.4,
      "p95": 418.1,
      "p99": 470.3,
      "max": 470.3
    },
    "read_and_decode": {
      "p50": 10.8,
      "p95": 45.0,
      "p99": 54.4,
      "max": 54.4
    },
    "append_to_dynamodb": {
      "p50": 3011.5,
      "p95": 3711.0,
      "p99": 3890.9,
      "max": 3890.9
    },
    "project_and_publish": {
      "p50": 245.0,
      "p95": 425.9,
      "p99": 3919.4,
      "max": 3919.4
    }
  },
  "share_of_time": {
    "append_to_dynamodb": "81%",
    "project_and_publish": "12%",
    "stream_io": "7%"
  },
  "messages_published": 78,
  "final_score": [
    3,
    3
  ],
  "note": "One worker, one match, on a laptop against DynamoDB Local in Docker. Managed DynamoDB writes an order of magnitude faster; the projection figure is independent of the store. The pipeline shards by match, so throughput across matches scales with workers."
}
```

## page

```json
{
  "lite_page_bytes": 2706,
  "lite_page_kb": 2.6,
  "match_state_json_kb": 16.6,
  "javascript_required": false,
  "note": "The no-JavaScript match page at /m/<id>, gzip off. The interactive app progressively enhances from the same data."
}
```

## win_probability

```json
{
  "generated_at": "2026-09-20",
  "split": {
    "kind": "time-based, on a match-date boundary",
    "cutoff_date": "2023-10-07",
    "train_rows": 288288,
    "train_matches": 3168,
    "test_rows": 72163,
    "test_matches": 793,
    "source": "StatsBomb Open Data, every competition-season published"
  },
  "features": [
    "minute",
    "minutes_remaining",
    "score_diff",
    "red_card_diff",
    "xg_diff",
    "shots_diff",
    "shots_on_target_diff",
    "possession_diff",
    "elo_diff",
    "is_neutral_venue"
  ],
  "best_iteration": 83,
  "brier": {
    "lightgbm": 0.4042,
    "logistic_regression": 0.4114,
    "baseline_constant_prior": 0.6486,
    "baseline_score_decides": 0.4694
  },
  "log_loss": {
    "lightgbm": 0.697,
    "logistic_regression": 0.7081,
    "baseline_constant_prior": 1.0693,
    "baseline_score_decides": 0.8131
  },
  "reliability": [
    {
      "bin_lo": 0.0,
      "bin_hi": 0.1,
      "predicted": 0.0364,
      "observed": 0.0388,
      "n": 56280
    },
    {
      "bin_lo": 0.1,
      "bin_hi": 0.2,
      "predicted": 0.1453,
      "observed": 0.1467,
      "n": 34509
    },
    {
      "bin_lo": 0.2,
      "bin_hi": 0.3,
      "predicted": 0.2502,
      "observed": 0.2378,
      "n": 33585
    },
    {
      "bin_lo": 0.3,
      "bin_hi": 0.4,
      "predicted": 0.3446,
      "observed": 0.3389,
      "n": 23694
    },
    {
      "bin_lo": 0.4,
      "bin_hi": 0.5,
      "predicted": 0.4475,
      "observed": 0.442,
      "n": 14135
    },
    {
      "bin_lo": 0.5,
      "bin_hi": 0.6,
      "predicted": 0.5461,
      "observed": 0.5552,
      "n": 10218
    },
    {
      "bin_lo": 0.6,
      "bin_hi": 0.7,
      "predicted": 0.6516,
      "observed": 0.707,
      "n": 9114
    },
    {
      "bin_lo": 0.7,
      "bin_hi": 0.8,
      "predicted": 0.7504,
      "observed": 0.7801,
      "n": 8123
    },
    {
      "bin_lo": 0.8,
      "bin_hi": 0.9,
      "predicted": 0.848,
      "observed": 0.808,
      "n": 11199
    },
    {
      "bin_lo": 0.9,
      "bin_hi": 1.0,
      "predicted": 0.9657,
      "observed": 0.969,
      "n": 15632
    }
  ],
  "calibration_by_minute": [
    {
      "bucket": "0-15",
      "brier": 0.5316,
      "n": 11895
    },
    {
      "bucket": "15-30",
      "brier": 0.4925,
      "n": 11895
    },
    {
      "bucket": "30-45",
      "brier": 0.448,
      "n": 11895
    },
    {
      "bucket": "45-60",
      "brier": 0.3998,
      "n": 11895
    },
    {
      "bucket": "60-75",
      "brier": 0.3295,
      "n": 11895
    },
    {
      "bucket": "75-90",
      "brier": 0.2405,
      "n": 11895
    }
  ],
  "inference_ms_single_row": 0.102,
  "recompute_90_minute_series_ms": 0.189,
  "feature_importance": {
    "minute": 140523,
    "minutes_remaining": 13049,
    "score_diff": 1198270,
    "red_card_diff": 13681,
    "xg_diff": 70937,
    "shots_diff": 28092,
    "shots_on_target_diff": 72192,
    "possession_diff": 31711,
    "elo_diff": 354630,
    "is_neutral_venue": 3268
  },
  "exported_trees": 249
}
```
