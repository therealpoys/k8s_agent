import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from src.dedup import Deduplicator, _cr_name
from src.models import Finding


def _make_dedup() -> Deduplicator:
    with patch("src.dedup.k8s_config.load_incluster_config", side_effect=ConfigException):
        with patch("src.dedup.k8s_config.load_kube_config"):
            with patch("src.dedup.client.CustomObjectsApi"):
                return Deduplicator()


def _make_finding(
    source: str = "k8s_events",
    namespace: str = "default",
    resource: str = "pod/my-pod",
    fingerprint: str = "Pod:my-pod:BackOff",
    severity: str = "HIGH",
    message: str = "test message",
    recommendation: str | None = None,
) -> Finding:
    return Finding(
        source=source,
        namespace=namespace,
        resource=resource,
        severity=severity,
        message=message,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw=None,
        fingerprint=fingerprint,
        recommendation=recommendation,
    )


def _mock_config(namespaces: list[str] = None, lookback_minutes: int = 15) -> MagicMock:
    cfg = MagicMock()
    cfg.namespaces = namespaces if namespaces is not None else ["default"]
    cfg.dedup_lookback_minutes = lookback_minutes
    return cfg


class TestFilterNew:
    def test_filter_new_creates_cr_for_unseen_finding_and_keeps_it(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)

        result = dedup.filter_new([finding])

        assert result == [finding]
        dedup._api.create_namespaced_custom_object.assert_called_once()

    def test_filter_new_stores_message_on_created_cr(self):
        dedup = _make_dedup()
        finding = _make_finding(message="pod crashed with OOMKilled")
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)

        dedup.filter_new([finding])

        args = dedup._api.create_namespaced_custom_object.call_args.args
        body = args[-1]
        assert body["spec"]["message"] == "pod crashed with OOMKilled"
        assert body["spec"]["recommendation"] == ""

    def test_filter_new_drops_finding_with_existing_fresh_cr(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"count": 1, "lastSeen": "2026-01-01T00:00:00+00:00"}
        }

        result = dedup.filter_new([finding])

        assert result == []

    def test_filter_new_patches_last_seen_and_count_on_existing_cr(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"count": 3, "lastSeen": "2026-01-01T00:00:00+00:00"}
        }

        dedup.filter_new([finding])

        dedup._api.patch_namespaced_custom_object.assert_called_once()
        args = dedup._api.patch_namespaced_custom_object.call_args.args
        patch_body = args[-1]
        assert patch_body["spec"]["count"] == 4
        assert "lastSeen" in patch_body["spec"]
        assert patch_body["spec"]["message"] == "test message"

    def test_filter_new_fails_open_on_non_404_api_error(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=500)

        result = dedup.filter_new([finding])

        assert result == [finding]
        dedup._api.create_namespaced_custom_object.assert_not_called()

    def test_filter_new_keeps_finding_when_create_call_itself_fails(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)
        dedup._api.create_namespaced_custom_object.side_effect = ApiException(status=500)

        result = dedup.filter_new([finding])

        assert result == [finding]

    def test_filter_new_does_not_raise_when_patch_call_itself_fails(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"count": 1, "lastSeen": "2026-01-01T00:00:00+00:00"}
        }
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=500)

        result = dedup.filter_new([finding])

        assert result == []


class TestUpdateRecommendations:
    def test_patches_cr_with_recommendation(self):
        dedup = _make_dedup()
        finding = _make_finding(recommendation="Increase memory limit")

        dedup.update_recommendations([finding])

        dedup._api.patch_namespaced_custom_object.assert_called_once()
        args = dedup._api.patch_namespaced_custom_object.call_args.args
        patch_body = args[-1]
        assert patch_body["spec"]["recommendation"] == "Increase memory limit"

    def test_skips_finding_without_recommendation(self):
        dedup = _make_dedup()
        finding = _make_finding(recommendation=None)

        dedup.update_recommendations([finding])

        dedup._api.patch_namespaced_custom_object.assert_not_called()

    def test_does_not_raise_when_patch_fails(self):
        dedup = _make_dedup()
        finding = _make_finding(recommendation="Increase memory limit")
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=500)

        dedup.update_recommendations([finding])  # must not raise


class TestCleanupResolved:
    def test_cleanup_resolved_deletes_cr_older_than_lookback(self):
        dedup = _make_dedup()
        old_last_seen = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {"lastSeen": old_last_seen},
                }
            ]
        }

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_called_once()

    def test_cleanup_resolved_keeps_cr_within_lookback(self):
        dedup = _make_dedup()
        fresh_last_seen = datetime.now(timezone.utc).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {"lastSeen": fresh_last_seen},
                }
            ]
        }

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_not_called()

    def test_cleanup_resolved_continues_when_list_fails_for_one_namespace(self):
        dedup = _make_dedup()
        old_last_seen = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.side_effect = [
            ApiException(status=500),
            {
                "items": [
                    {"metadata": {"name": "abc123"}, "spec": {"lastSeen": old_last_seen}}
                ]
            },
        ]

        with patch("src.dedup.config", _mock_config(namespaces=["broken", "ok"], lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_called_once()

    def test_cleanup_resolved_ignores_404_race_on_delete(self):
        dedup = _make_dedup()
        old_last_seen = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {"metadata": {"name": "abc123"}, "spec": {"lastSeen": old_last_seen}}
            ]
        }
        dedup._api.delete_namespaced_custom_object.side_effect = ApiException(status=404)

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()  # must not raise


class TestCrName:
    def test_cr_name_is_deterministic_and_valid_k8s_name(self):
        finding = _make_finding()

        name_a = _cr_name(finding)
        name_b = _cr_name(finding)

        assert name_a == name_b
        assert re.fullmatch(r"[a-f0-9]+", name_a)
        assert len(name_a) == 40

    def test_cr_name_differs_for_different_fingerprints(self):
        finding_a = _make_finding(fingerprint="Pod:my-pod:BackOff")
        finding_b = _make_finding(fingerprint="Pod:my-pod:FailedMount")

        assert _cr_name(finding_a) != _cr_name(finding_b)
