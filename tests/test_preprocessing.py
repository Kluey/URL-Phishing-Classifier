import pytest

from components.preprocessing import normalize_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.google.com", "google.com"),
        ("http://google.com", "google.com"),
        ("google.com", "google.com"),
        ("www.google.com", "google.com"),
        ("HTTPS://WWW.Google.com/Path", "Google.com/Path"),
        ("https://www2.example.com/x", "example.com/x"),
        ("https://wwwexample.com", "wwwexample.com"),
        ("  https://a.com ", "a.com"),
        ("ftp://x.org/f", "x.org/f"),
        ("https://www.google.com/search?q=http://evil.com", "google.com/search?q=http://evil.com"),
        ("https://www.", ""),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_spellings_of_one_site_collapse_to_one_input():
    variants = ["google.com", "http://google.com", "https://google.com", "https://www.google.com"]
    assert len({normalize_url(v) for v in variants}) == 1