import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from kubernetes.client.exceptions import ApiException
from kubernetes.config import ConfigException

from src.dedup import Deduplicator, _cr_name
from src.models import Finding
from src.plugins.identity import resource_identity


def _make_dedup() -> Deduplicator:
    with patch("src.dedup.k8s_config.load_incluster_config", side_effect=ConfigException):
        with patch("src.dedup.k8s_config.load_kube_config"):
            with patch("src.dedup.client.CustomObjectsApi"):
                return Deduplicator()


def _make_finding(
    source: str = "k8s_events",
    namespace: str = "default",
    resource: str = "pod/my-pod",
    identity: str = "pod/my-pod",
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
        identity=identity,
        recommendation=recommendation,
    )


def _make_entry(
    source: str = "k8s_events",
    fingerprint: str = "Pod:my-pod:BackOff",
    severity: str = "HIGH",
    message: str = "test message",
    recommendation: str = "",
    first_seen: str = "2026-01-01T00:00:00+00:00",
    last_seen: str = "2026-01-01T00:00:00+00:00",
    count: int = 1,
) -> dict:
    return {
        "source": source,
        "fingerprint": fingerprint,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
        "firstSeen": first_seen,
        "lastSeen": last_seen,
        "count": count,
    }


def _mock_config(namespaces: list[str] = None, lookback_minutes: int = 15) -> MagicMock:
    cfg = MagicMock()
    cfg.namespaces = namespaces if namespaces is not None else ["default"]
    cfg.dedup_lookback_minutes = lookback_minutes
    return cfg


class TestFilterNew:
    def test_filter_new_creates_cr_with_single_finding_for_unseen_identity(self):
        dedup = _make_dedup()
        finding = _make_finding()
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=404)

        result = dedup.filter_new([finding])

        assert result == [finding]
        dedup._api.create_namespaced_custom_object.assert_called_once()
        args = dedup._api.create_namespaced_custom_object.call_args.args
        body = args[-1]
        assert body["spec"]["resource"] == "pod/my-pod"
        assert body["spec"]["findingCount"] == 1
        assert body["spec"]["findings"][0]["fingerprint"] == "Pod:my-pod:BackOff"

    def test_filter_new_groups_multiple_findings_of_same_identity_into_one_cr(self):
        dedup = _make_dedup()
        finding_a = _make_finding(fingerprint="Pod:my-pod:BackOff")
        finding_b = _make_finding(fingerprint="Pod:my-pod:FailedMount")
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=404)

        result = dedup.filter_new([finding_a, finding_b])

        assert result == [finding_a, finding_b]
        dedup._api.get_namespaced_custom_object.assert_called_once()
        dedup._api.create_namespaced_custom_object.assert_called_once()
        body = dedup._api.create_namespaced_custom_object.call_args.args[-1]
        assert body["spec"]["findingCount"] == 2

    def test_filter_new_returns_full_group_when_one_finding_is_new(self):
        dedup = _make_dedup()
        known = _make_finding(fingerprint="Pod:my-pod:BackOff")
        new_finding = _make_finding(fingerprint="Pod:my-pod:FailedMount")
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"findings": [_make_entry(fingerprint="Pod:my-pod:BackOff")]}
        }

        result = dedup.filter_new([known, new_finding])

        assert result == [known, new_finding]
        dedup._api.patch_namespaced_custom_object.assert_called_once()
        patch_body = dedup._api.patch_namespaced_custom_object.call_args.args[-1]
        assert patch_body["spec"]["findingCount"] == 2

    def test_filter_new_skips_group_when_nothing_new(self):
        dedup = _make_dedup()
        finding = _make_finding(fingerprint="Pod:my-pod:BackOff")
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"findings": [_make_entry(fingerprint="Pod:my-pod:BackOff", count=3)]}
        }

        result = dedup.filter_new([finding])

        assert result == []
        dedup._api.patch_namespaced_custom_object.assert_called_once()
        patch_body = dedup._api.patch_namespaced_custom_object.call_args.args[-1]
        assert patch_body["spec"]["findings"][0]["count"] == 4

    def test_filter_new_preserves_untouched_entries_in_merge(self):
        dedup = _make_dedup()
        entry_a = _make_entry(source="pod_logs", fingerprint="my-pod/app", message="stays as-is")
        new_finding = _make_finding(source="k8s_events", fingerprint="Pod:my-pod:BackOff")
        dedup._api.get_namespaced_custom_object.return_value = {"spec": {"findings": [entry_a]}}

        dedup.filter_new([new_finding])

        patch_body = dedup._api.patch_namespaced_custom_object.call_args.args[-1]
        findings = patch_body["spec"]["findings"]
        assert len(findings) == 2
        untouched = next(e for e in findings if e["fingerprint"] == "my-pod/app")
        assert untouched == entry_a
        added = next(e for e in findings if e["fingerprint"] == "Pod:my-pod:BackOff")
        assert added["source"] == "k8s_events"

    def test_filter_new_fails_open_on_non_404_api_error(self):
        dedup = _make_dedup()
        finding_a = _make_finding(fingerprint="Pod:my-pod:BackOff")
        finding_b = _make_finding(fingerprint="Pod:my-pod:FailedMount")
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=500)

        result = dedup.filter_new([finding_a, finding_b])

        assert result == [finding_a, finding_b]
        dedup._api.create_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_not_called()

    def test_filter_new_groups_findings_from_different_plugins_with_same_pod_into_one_cr(self):
        dedup = _make_dedup()
        # Vor der Identity-Normalisierung lieferten Plugins unterschiedliche kind-Schreibweisen
        # (z.B. k8s_events "Pod" vs. Trivy-Operator-Label "pod") — resource_identity() lowercased
        # beide auf denselben String, wodurch sie hier in dieselbe Gruppe/CR fallen müssen.
        finding_a = _make_finding(
            source="k8s_events",
            identity=resource_identity("Pod", "my-pod"),
            fingerprint="Pod:my-pod:BackOff",
        )
        finding_b = _make_finding(
            source="trivy",
            identity=resource_identity("pod", "my-pod"),
            fingerprint="pod/my-pod:app",
        )
        dedup._api.get_namespaced_custom_object.side_effect = ApiException(status=404)
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=404)

        result = dedup.filter_new([finding_a, finding_b])

        assert result == [finding_a, finding_b]
        dedup._api.create_namespaced_custom_object.assert_called_once()
        body = dedup._api.create_namespaced_custom_object.call_args.args[-1]
        assert body["spec"]["findingCount"] == 2

    def test_filter_new_skips_api_call_for_findings_without_namespace(self):
        dedup = _make_dedup()
        finding = _make_finding(namespace="", identity="unknown")

        result = dedup.filter_new([finding])

        assert result == [finding]
        dedup._api.get_namespaced_custom_object.assert_not_called()
        dedup._api.create_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_not_called()


class TestUpdateRecommendations:
    def test_update_recommendations_patches_matching_entry_only(self):
        dedup = _make_dedup()
        entry_a = _make_entry(source="k8s_events", fingerprint="Pod:my-pod:BackOff")
        entry_b = _make_entry(source="trivy", fingerprint="ReplicaSet/my-app:my-container")
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"findings": [entry_a, entry_b]}
        }
        finding = _make_finding(
            source="k8s_events",
            fingerprint="Pod:my-pod:BackOff",
            recommendation="Increase memory limit",
        )

        dedup.update_recommendations([finding])

        dedup._api.patch_namespaced_custom_object.assert_called_once()
        patch_body = dedup._api.patch_namespaced_custom_object.call_args.args[-1]
        findings = patch_body["spec"]["findings"]
        patched = next(e for e in findings if e["fingerprint"] == "Pod:my-pod:BackOff")
        untouched = next(e for e in findings if e["fingerprint"] == "ReplicaSet/my-app:my-container")
        assert patched["recommendation"] == "Increase memory limit"
        assert untouched["recommendation"] == ""

    def test_skips_finding_without_recommendation(self):
        dedup = _make_dedup()
        finding = _make_finding(recommendation=None)

        dedup.update_recommendations([finding])

        dedup._api.get_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_not_called()

    def test_does_not_raise_when_patch_fails(self):
        dedup = _make_dedup()
        dedup._api.get_namespaced_custom_object.return_value = {
            "spec": {"findings": [_make_entry()]}
        }
        finding = _make_finding(recommendation="Increase memory limit")
        dedup._api.patch_namespaced_custom_object.side_effect = ApiException(status=500)

        dedup.update_recommendations([finding])  # must not raise

    def test_skips_api_call_for_findings_without_namespace(self):
        dedup = _make_dedup()
        finding = _make_finding(namespace="", identity="unknown", recommendation="n/a")

        dedup.update_recommendations([finding])

        dedup._api.get_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_not_called()


class TestCleanupResolved:
    def test_cleanup_resolved_removes_stale_entry_keeps_fresh_entry_in_same_cr(self):
        dedup = _make_dedup()
        stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {
                        "findings": [
                            _make_entry(fingerprint="stale-one", last_seen=stale),
                            _make_entry(fingerprint="fresh-one", last_seen=fresh),
                        ]
                    },
                }
            ]
        }

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_called_once()
        patch_body = dedup._api.patch_namespaced_custom_object.call_args.args[-1]
        assert patch_body["spec"]["findingCount"] == 1
        assert patch_body["spec"]["findings"][0]["fingerprint"] == "fresh-one"

    def test_cleanup_resolved_deletes_cr_when_all_entries_stale(self):
        dedup = _make_dedup()
        stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {"findings": [_make_entry(fingerprint="stale-one", last_seen=stale)]},
                }
            ]
        }

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_called_once()
        dedup._api.patch_namespaced_custom_object.assert_not_called()

    def test_cleanup_resolved_keeps_cr_when_all_entries_fresh(self):
        dedup = _make_dedup()
        fresh = datetime.now(timezone.utc).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {"findings": [_make_entry(fingerprint="fresh-one", last_seen=fresh)]},
                }
            ]
        }

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_not_called()
        dedup._api.patch_namespaced_custom_object.assert_not_called()

    def test_cleanup_resolved_continues_when_list_fails_for_one_namespace(self):
        dedup = _make_dedup()
        stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.side_effect = [
            ApiException(status=500),
            {
                "items": [
                    {
                        "metadata": {"name": "abc123"},
                        "spec": {"findings": [_make_entry(fingerprint="stale-one", last_seen=stale)]},
                    }
                ]
            },
        ]

        with patch("src.dedup.config", _mock_config(namespaces=["broken", "ok"], lookback_minutes=15)):
            dedup.cleanup_resolved()

        dedup._api.delete_namespaced_custom_object.assert_called_once()

    def test_cleanup_resolved_ignores_404_race_on_delete(self):
        dedup = _make_dedup()
        stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        dedup._api.list_namespaced_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "abc123"},
                    "spec": {"findings": [_make_entry(fingerprint="stale-one", last_seen=stale)]},
                }
            ]
        }
        dedup._api.delete_namespaced_custom_object.side_effect = ApiException(status=404)

        with patch("src.dedup.config", _mock_config(lookback_minutes=15)):
            dedup.cleanup_resolved()  # must not raise


class TestCrName:
    def test_cr_name_is_deterministic_and_valid_k8s_name(self):
        name_a = _cr_name("default", "pod/my-pod")
        name_b = _cr_name("default", "pod/my-pod")

        assert name_a == name_b
        assert re.fullmatch(r"[a-f0-9]+", name_a)
        assert len(name_a) == 40

    def test_cr_name_differs_for_different_identities(self):
        name_a = _cr_name("default", "pod/my-pod")
        name_b = _cr_name("default", "pod/other-pod")

        assert name_a != name_b
