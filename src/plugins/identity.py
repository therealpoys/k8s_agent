import re

# Kubernetes generiert Namens-Suffixe aus einem vokal-freien Alphabet (rand.String),
# damit sind sie von echten Wort-Segmenten sicher unterscheidbar.
_POD_HASH = re.compile(r"^[bcdfghjklmnpqrstvwxz0-9]{5}$")
_TEMPLATE_HASH = re.compile(r"^[bcdfghjklmnpqrstvwxz0-9]{8,10}$")
_JOB_TIMESTAMP = re.compile(r"^[0-9]{6,10}$")


def stable_name(name: str) -> str:
    parts = name.split("-")
    while len(parts) > 1 and (
        _POD_HASH.match(parts[-1])
        or _TEMPLATE_HASH.match(parts[-1])
        or _JOB_TIMESTAMP.match(parts[-1])
    ):
        parts.pop()
    return "-".join(parts)
