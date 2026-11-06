import pytest

from components.preprocessing import normalize_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.google.com", "google.com"),
        ("http://google.com", "google.com"),
        ("google.com", "google.com"),
        ("www.google.com", "google.com"),
        ("HTTPS://WWW.Google.com/Path", "google.com"),
        ("https://www2.example.com/x", "example.com"),
        ("https://wwwexample.com", "wwwexample.com"),
        ("  https://a.com ", "a.com"),
        ("ftp://x.org/f", "x.org"),
        ("https://www.google.com/search?q=http://evil.com", "google.com"),
        ("https://a.com?next=/login", "a.com"),
        ("https://a.com#frag", "a.com"),
        ("https://a.com:8080/x", "a.com"),
        ("https://paypal.com@evil.com/login", "evil.com"),
        ("http://192.168.1.1/login", "192.168.1.1"),
        ("https://a.com./x", "a.com"),
        ("https://[::1/x", "[::1"),
        ("https://www.", ""),
        ("", ""),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_spellings_of_one_site_collapse_to_one_input():
    variants = [
        "google.com", "http://google.com", "https://google.com",
        "https://www.google.com", "https://www.google.com/maps?q=x",
    ]
    assert len({normalize_url(v) for v in variants}) == 1
