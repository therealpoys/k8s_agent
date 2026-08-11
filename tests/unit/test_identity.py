from src.plugins.identity import stable_name


class TestStableName:
    def test_strips_cronjob_pod_suffix_and_job_timestamp(self):
        assert stable_name("k8s-agent-k8s-agent-29773142-s58hq") == "k8s-agent-k8s-agent"

    def test_strips_job_timestamp_only(self):
        assert stable_name("k8s-agent-k8s-agent-29773142") == "k8s-agent-k8s-agent"

    def test_strips_replicaset_template_hash_and_pod_suffix(self):
        assert stable_name("scan-vulnerabilityreport-f4645f7bb-m6sn5") == "scan-vulnerabilityreport"

    def test_strips_deployment_pod_name(self):
        assert stable_name("myapp-7d9f8c6b5-xk2pl") == "myapp"

    def test_leaves_plain_name_untouched(self):
        assert stable_name("crashloop") == "crashloop"

    def test_leaves_hand_named_pod_untouched(self):
        assert stable_name("broken-image") == "broken-image"

    def test_does_not_strip_a_real_word_that_looks_short(self):
        assert stable_name("my-service-mysql") == "my-service-mysql"
