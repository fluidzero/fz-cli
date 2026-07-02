"""Tests for the composite-run empty-result guard.

Live finding (2026-07-02): a degraded v1 pipeline can mark a run 'completed'
with error=None while extracting nothing (fields_extracted=0, hollow per-field
scaffolding dicts). The composite commands must warn instead of presenting
that as success.
"""

from __future__ import annotations

from fz_cli.commands.batch import _results_look_empty


def test_no_results_is_empty():
    assert _results_look_empty([])


def test_explicit_zero_fields_extracted_is_empty_despite_scaffolding():
    # Mirrors the real degraded ATLAS result shape: per-field dicts exist but
    # are hollow, and the pipeline explicitly reports fields_extracted=0.
    degraded = {
        "data": {
            "field_results": {
                "total_revenue": {"error": None, "sources": [], "confidence": 0.0},
                "company_name": {"error": None, "sources": [], "confidence": 0.0},
            },
            "fields_extracted": 0,
        },
    }
    assert _results_look_empty([degraded])


def test_metadata_fields_extracted_zero_is_empty():
    assert _results_look_empty([{"data": {}, "resultMetadata": {"fields_extracted": 0}}])


def test_real_values_not_empty():
    assert not _results_look_empty([{"data": {"total_revenue": "$7,192 million"}}])


def test_fields_extracted_positive_not_empty():
    assert not _results_look_empty(
        [{"data": {}, "resultMetadata": {"fields_extracted": 5}}]
    )
