from scripts import security_scan


def test_product_html_inline_script_remains_forbidden():
    assert security_scan.inline_script_conflicts_with_csp(
        "web/index.html",
        "<main></main><script>window.bad = true;</script>",
    )


def test_hoster_fixture_inline_player_script_is_inert():
    assert not security_scan.inline_script_conflicts_with_csp(
        "tests/fixtures/hoster-sentinel/normal.html",
        '<script>var sources = {"hls":"https://media.example/video.m3u8"};</script>',
    )


def test_arbitrary_test_html_does_not_bypass_csp_scan():
    assert security_scan.inline_script_conflicts_with_csp(
        "tests/unrelated-page.html",
        "<script>window.bad = true;</script>",
    )


def test_external_script_tag_is_allowed_by_strict_csp_scan():
    assert not security_scan.inline_script_conflicts_with_csp(
        "web/index.html",
        '<script src="/js/app.js"></script>',
    )
