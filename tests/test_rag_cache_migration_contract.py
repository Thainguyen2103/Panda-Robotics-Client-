"""Fixture-only specification tests for the proposed RAG cache v2 contract.

These tests intentionally do not call or modify the production cache loader.
They document the acceptance policy to use when a separately reviewed migration
is implemented.
"""

import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


EXPECTED = {
    "format_version": 2,
    "model_id": "intfloat/multilingual-e5-small",
    "model_revision": "fixture-revision",
    "data_fingerprint": "sha256:fixture-corpus",
    "vector_count": 2,
    "dimension": 3,
    "dtype": "float32",
}


def validate_fixture_cache(path: Path, expected=EXPECTED) -> tuple[bool, str]:
    """Reference policy only; not the production cache validation function."""
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {"embeddings", "metadata_json"}:
                return False, "missing_or_unknown_metadata"
            vectors = archive["embeddings"]
            metadata = json.loads(str(archive["metadata_json"].item()))
    except Exception:
        return False, "unreadable_archive"

    for field in (
        "format_version",
        "model_id",
        "model_revision",
        "data_fingerprint",
        "vector_count",
        "dimension",
        "dtype",
    ):
        if metadata.get(field) != expected[field]:
            return False, f"metadata_mismatch:{field}"
    if vectors.shape != (expected["vector_count"], expected["dimension"]):
        return False, "shape_mismatch"
    if vectors.dtype != np.dtype(expected["dtype"]):
        return False, "dtype_mismatch"
    if not np.isfinite(vectors).all():
        return False, "non_finite_values"
    return True, "valid"


def publish_fixture_cache(destination: Path, metadata, vectors, fail_at=None) -> bool:
    """Test-only reference writer; deliberately not connected to production."""
    temp_path = destination.with_name(destination.name + f".{os.getpid()}.pending.npz")
    previous = destination.read_bytes() if destination.exists() else None
    try:
        if fail_at == "write":
            raise OSError("injected fixture write failure")
        np.savez_compressed(
            temp_path,
            embeddings=vectors,
            metadata_json=np.asarray(json.dumps(metadata)),
        )
        valid, _ = validate_fixture_cache(temp_path)
        if fail_at == "validate" or not valid:
            return False
        if fail_at == "replace":
            raise OSError("injected fixture replacement failure")
        os.replace(temp_path, destination)
        if fail_at == "post_replace":
            raise OSError("injected post-replacement verification failure")
        return True
    except OSError:
        if fail_at == "post_replace" and previous is not None:
            destination.write_bytes(previous)
        return False
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _fixture_writer_process(destination: str, value: float, delay: float, fail_at=None):
    """Independent process writer used only against a temporary fixture."""
    time.sleep(delay)
    path = Path(destination)
    metadata = dict(EXPECTED)
    vectors = np.asarray([[value, 0, 0], [0, value, 0]], dtype=np.float32)
    if not publish_fixture_cache(path, metadata, vectors, fail_at=fail_at) and fail_at is None:
        raise RuntimeError("fixture writer unexpectedly failed")


def fixture_load_or_fallback(path: Path, model_factory):
    """Mocked policy contract; does not load an actual model or production code."""
    valid, _ = validate_fixture_cache(path)
    if valid:
        with np.load(path, allow_pickle=False) as archive:
            return "cache", archive["embeddings"].copy()
    try:
        return "rebuilt", model_factory()
    except Exception:
        return "fallback", None


class RagCacheMigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write_cache(self, *, metadata=None, vectors=None, filename="fixture.npz"):
        path = self.directory / filename
        if vectors is None:
            vectors = np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        arrays = {"embeddings": vectors}
        if metadata is not None:
            arrays["metadata_json"] = np.asarray(json.dumps(metadata))
        np.savez_compressed(path, **arrays)
        return path

    def test_accepts_complete_matching_fixture(self):
        self.assertEqual(validate_fixture_cache(self.write_cache(metadata=EXPECTED)), (True, "valid"))

    def test_rejects_each_stale_or_incompatible_metadata_field(self):
        for field, value in (
            ("data_fingerprint", "sha256:other-corpus"),
            ("model_id", "other/model"),
            ("model_revision", "other-revision"),
            ("format_version", 1),
            ("dimension", 384),
            ("vector_count", 99),
        ):
            with self.subTest(field=field):
                metadata = dict(EXPECTED, **{field: value})
                self.assertFalse(validate_fixture_cache(self.write_cache(metadata=metadata))[0])

    def test_rejects_shape_dtype_nan_and_inf(self):
        cases = (
            (np.zeros((1, 3), dtype=np.float32), "shape"),
            (np.zeros((2, 384), dtype=np.float32), "shape"),
            (np.zeros((2, 3), dtype=np.float64), "dtype"),
            (np.asarray([[np.nan, 0, 0], [0, 1, 0]], dtype=np.float32), "finite"),
            (np.asarray([[np.inf, 0, 0], [0, 1, 0]], dtype=np.float32), "finite"),
        )
        for vectors, reason in cases:
            with self.subTest(reason=reason, shape=vectors.shape, dtype=vectors.dtype):
                valid, actual_reason = validate_fixture_cache(self.write_cache(metadata=EXPECTED, vectors=vectors))
                self.assertFalse(valid)
                self.assertIn(reason, actual_reason)

    def test_rejects_legacy_cache_without_metadata(self):
        legacy = self.write_cache(metadata=None)
        self.assertEqual(validate_fixture_cache(legacy), (False, "missing_or_unknown_metadata"))

    def test_rejects_corrupt_archive(self):
        path = self.directory / "broken.npz"
        path.write_bytes(b"partial archive bytes")
        self.assertEqual(validate_fixture_cache(path), (False, "unreadable_archive"))

    def test_ignores_unfinished_temp_when_no_committed_cache_exists(self):
        # Proposed writer uses a sibling temp path; an interrupted file must
        # never be treated as the committed cache.
        partial = self.directory / "fixture.tmp.npz"
        partial.write_bytes(b"partial write")
        committed = self.directory / "fixture.npz"
        self.assertFalse(committed.exists())
        self.assertFalse(validate_fixture_cache(committed)[0])

    def test_rejects_missing_metadata_fields_and_embeddings(self):
        for metadata in (
            {key: value for key, value in EXPECTED.items() if key != "model_revision"},
            {key: value for key, value in EXPECTED.items() if key != "dtype"},
        ):
            with self.subTest(missing=set(EXPECTED) - set(metadata)):
                self.assertFalse(validate_fixture_cache(self.write_cache(metadata=metadata))[0])

        missing_embeddings = self.directory / "missing_embeddings.npz"
        np.savez_compressed(missing_embeddings, metadata_json=np.asarray(json.dumps(EXPECTED)))
        self.assertEqual(validate_fixture_cache(missing_embeddings), (False, "missing_or_unknown_metadata"))

    def test_fixture_writer_preserves_old_cache_on_write_validation_and_replace_failure(self):
        destination = self.write_cache(metadata=EXPECTED, filename="committed.npz")
        original = destination.read_bytes()
        vectors = np.asarray([[0, 1, 0], [1, 0, 0]], dtype=np.float32)

        for failure in ("write", "validate", "replace", "post_replace"):
            with self.subTest(failure=failure):
                self.assertFalse(publish_fixture_cache(destination, EXPECTED, vectors, fail_at=failure))
                self.assertEqual(destination.read_bytes(), original)
                self.assertFalse(destination.with_name(destination.name + f".{os.getpid()}.pending.npz").exists())

    def test_fixture_writer_publishes_and_reopens_valid_cache(self):
        destination = self.directory / "published.npz"
        vectors = np.asarray([[0, 1, 0], [1, 0, 0]], dtype=np.float32)
        self.assertTrue(publish_fixture_cache(destination, EXPECTED, vectors))
        self.assertEqual(validate_fixture_cache(destination), (True, "valid"))
        with np.load(destination, allow_pickle=False) as archive:
            np.testing.assert_array_equal(archive["embeddings"], vectors)

    def test_two_fixture_process_writers_leave_one_valid_archive(self):
        destination = self.directory / "contended.npz"
        context = multiprocessing.get_context("spawn")
        writers = [
            context.Process(target=_fixture_writer_process, args=(str(destination), 1.0, 0.0)),
            context.Process(target=_fixture_writer_process, args=(str(destination), 2.0, 0.0)),
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join(timeout=15)
        for writer in writers:
            if writer.is_alive():
                writer.terminate()
                writer.join()
            self.assertEqual(writer.exitcode, 0)
        self.assertEqual(validate_fixture_cache(destination), (True, "valid"))

    def test_offline_model_unavailable_policy_is_fixture_only(self):
        self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_TELEMETRY"), "1")
        # No model loader is imported or invoked by this contract test. It only
        # records that an invalid cache must not be treated as a rebuild success.
        invalid = self.write_cache(metadata=None)
        self.assertFalse(validate_fixture_cache(invalid)[0])

    def test_valid_cache_is_used_without_model_factory(self):
        cache = self.write_cache(metadata=EXPECTED)
        def unavailable_model():
            raise AssertionError("model factory must not be called for a valid cache")
        source, vectors = fixture_load_or_fallback(cache, unavailable_model)
        self.assertEqual(source, "cache")
        self.assertEqual(vectors.shape, (2, 3))

    def test_invalid_cache_and_missing_model_falls_back_without_changing_cache(self):
        cache = self.write_cache(metadata=None)
        original = cache.read_bytes()
        def missing_local_model():
            raise FileNotFoundError("fixture has no local model")
        source, vectors = fixture_load_or_fallback(cache, missing_local_model)
        self.assertEqual((source, vectors), ("fallback", None))
        self.assertEqual(cache.read_bytes(), original)

    def test_failed_concurrent_writer_does_not_destroy_successful_cache(self):
        destination = self.directory / "one_failed_writer.npz"
        context = multiprocessing.get_context("spawn")
        writers = [
            context.Process(target=_fixture_writer_process, args=(str(destination), 1.0, 0.0, "write")),
            context.Process(target=_fixture_writer_process, args=(str(destination), 2.0, 0.0)),
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join(timeout=15)
        for writer in writers:
            if writer.is_alive():
                writer.terminate()
                writer.join()
            self.assertEqual(writer.exitcode, 0)
        self.assertEqual(validate_fixture_cache(destination), (True, "valid"))


if __name__ == "__main__":
    unittest.main()
