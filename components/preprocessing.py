import re

_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_WWW = re.compile(r"^www\d*\.", re.IGNORECASE)


def normalize_url(url):
    url = _SCHEME.sub("", url.strip(), count=1)
    return _WWW.sub("", url, count=1)