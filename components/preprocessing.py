import re
from urllib.parse import urlsplit

_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_WWW = re.compile(r"^www\d*\.", re.IGNORECASE)


def normalize_url(url):
    """Reduce a URL to the model input: its lowercase hostname without a leading www.

    Every legitimate URL in PhiUSIIL is a bare hostname, so a model that sees paths
    learns "has a path = phishing". Only the hostname is kept, in training and inference.
    """
    rest = _SCHEME.sub("", url.strip(), count=1)
    try:
        host = urlsplit("//" + rest).hostname or ""
    except ValueError:  # malformed netloc, e.g. an unbalanced IPv6 bracket
        host = re.split(r"[/?#]", rest, maxsplit=1)[0].lower()
    return _WWW.sub("", host, count=1).rstrip(".")
