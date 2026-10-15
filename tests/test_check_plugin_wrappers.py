"""Proves check_plugin_wrappers.py FAILS on each kind of drift, not just that it
passes on the files as they are today. Offline: check() takes XML text, so no
.plg is fetched here."""

import contextlib
import io
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_plugin_wrappers as cpw
from check_plugin_wrappers import check, check_profile

URL = "https://github.com/example/demo/releases/latest/download/demo.plg"

FIELDS = {
    "Name": "Demo",
    "Overview": "A demo plugin.",
    "PluginURL": URL,
    "PluginAuthor": "example",
    "Support": "https://github.com/example/demo/issues",
    "Project": "https://github.com/example/demo",
    "Category": "Tools:System",
    "IconFA": "hdd-o",
    "MinVer": "7.0.0",
}

ATTRS = {
    "name": "demo",
    "pluginURL": URL,
    "support": "https://github.com/example/demo/issues",
    "min": "7.0.0",
    "icon": "hdd-o",
}


def wrapper(**overrides):
    fields = {**FIELDS, **overrides}
    body = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items() if v is not None)
    return f"<Plugin>{body}</Plugin>"


def plg(**overrides):
    attrs = {**ATTRS, **overrides}
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v is not None)
    # The comment quotes a DIFFERENT icon= on purpose: a text search would match
    # it, which is the bug the XML-parsing approach exists to avoid.
    return f'<?xml version="1.0"?>\n<!-- icon="bolt" was considered -->\n<PLUGIN {body}></PLUGIN>'


class CheckTest(unittest.TestCase):
    def assertFails(self, errors, needle):
        self.assertTrue(any(needle in e for e in errors), f"expected a failure mentioning {needle!r}, got {errors}")

    def test_agreeing_pair_passes(self):
        self.assertEqual(check(wrapper(), plg()), [])

    def test_plugin_url_mismatch_fails(self):
        self.assertFails(check(wrapper(), plg(pluginURL=URL + "?x")), "PluginURL")

    def test_plugin_url_is_byte_exact(self):
        self.assertFails(check(wrapper(), plg(pluginURL=URL.replace("github", "GitHub"))), "PluginURL")

    def test_plg_without_plugin_url_fails(self):
        self.assertFails(check(wrapper(), plg(pluginURL=None)), "pluginURL")

    def test_icon_mismatch_fails(self):
        self.assertFails(check(wrapper(), plg(icon="bolt")), "IconFA")

    def test_icon_in_comment_is_ignored(self):
        # plg() always carries a comment quoting icon="bolt"; only the real
        # attribute counts.
        self.assertEqual(check(wrapper(IconFA="hdd-o"), plg(icon="hdd-o")), [])

    def test_icon_fa_prefix_is_spelling_not_identity(self):
        self.assertEqual(check(wrapper(IconFA="desktop"), plg(icon="fa-desktop")), [])
        self.assertFails(check(wrapper(IconFA="desktop"), plg(icon="fa-bolt")), "IconFA")

    def test_min_mismatch_fails(self):
        self.assertFails(check(wrapper(), plg(min="6.12.0")), "MinVer")

    def test_max_mismatch_fails(self):
        self.assertFails(check(wrapper(MaxVer="7.2.0"), plg(max="7.1.0")), "MaxVer")

    def test_attribute_on_one_side_only_is_skipped(self):
        self.assertEqual(check(wrapper(MaxVer="7.2.0"), plg()), [])
        self.assertEqual(check(wrapper(MinVer=None), plg()), [])

    def test_support_beneath_plg_root_passes(self):
        self.assertEqual(check(wrapper(), plg(support="https://github.com/example/demo/")), [])

    def test_support_prefix_without_path_boundary_fails(self):
        self.assertFails(
            check(wrapper(Support="https://github.com/example/demo/issues.evil.example/x"), plg()),
            "Support",
        )

    def test_support_elsewhere_fails(self):
        self.assertFails(check(wrapper(Support="https://forums.unraid.net/topic/1"), plg()), "Support")

    def test_missing_required_field_fails(self):
        for name in ("Name", "Overview", "PluginURL", "PluginAuthor"):
            with self.subTest(name=name):
                self.assertFails(check(wrapper(**{name: None}), plg()), "required by CA")

    def test_missing_convention_field_fails(self):
        for name in ("Support", "Project", "Category"):
            with self.subTest(name=name):
                self.assertFails(check(wrapper(**{name: None}), plg()), "repo convention")

    def test_wrong_wrapper_root_fails(self):
        self.assertFails(check("<Container/>", plg()), "<Plugin>")

    def test_wrong_plg_root_fails(self):
        self.assertFails(check(wrapper(), "<NOTPLUGIN/>"), "<PLUGIN>")

    def test_plugin_url_whitespace_fails(self):
        # Byte-exact means exact: whitespace CA may not trim is a mismatch.
        self.assertFails(check(wrapper(PluginURL=f"\n  {URL}  \n"), plg()), "PluginURL")

    def test_doctype_entity_in_plugin_url_passes(self):
        # Real .plg files carry a DOCTYPE and commonly build pluginURL from
        # internal entities; a stricter parser that forbade DTDs would break
        # on them.
        src = (
            '<?xml version="1.0"?>\n<!DOCTYPE PLUGIN [\n'
            '<!ENTITY base "https://github.com/example/demo/releases/latest/download">\n]>\n'
            '<PLUGIN name="demo" pluginURL="&base;/demo.plg" icon="hdd-o" min="7.0.0"></PLUGIN>'
        )
        self.assertEqual(check(wrapper(), src), [])

    def test_external_entity_is_not_resolved(self):
        src = (
            '<?xml version="1.0"?>\n<!DOCTYPE PLUGIN [\n'
            '<!ENTITY x SYSTEM "file:///etc/hostname">\n]>\n'
            '<PLUGIN pluginURL="&x;"></PLUGIN>'
        )
        with self.assertRaises(ET.ParseError):
            check(wrapper(), src)


class ProfileTest(unittest.TestCase):
    def test_either_root_with_profile_passes(self):
        for tag in ("RepositoryInfo", "CommunityApplications"):
            with self.subTest(tag=tag):
                self.assertEqual(check_profile(f"<{tag}><Profile>x</Profile></{tag}>"), [])

    def test_empty_profile_fails(self):
        self.assertTrue(check_profile("<RepositoryInfo><Profile> </Profile></RepositoryInfo>"))

    def test_unknown_root_fails(self):
        self.assertTrue(check_profile("<Container><Profile>x</Profile></Container>"))


class FakeResponse(io.BytesIO):
    def __init__(self, body, final_url=URL):
        super().__init__(body)
        self.final_url = final_url

    def geturl(self):
        return self.final_url


class FetchTest(unittest.TestCase):
    def test_non_https_refused_without_a_request(self):
        with mock.patch.object(cpw._OPENER, "open") as urlopen:
            with self.assertRaises(ValueError):
                cpw.fetch("http://example.com/demo.plg")
            urlopen.assert_not_called()

    def test_redirect_to_http_refused(self):
        redirected = FakeResponse(b"<PLUGIN/>", "http://evil.example/x")
        with mock.patch.object(cpw._OPENER, "open", return_value=redirected), self.assertRaisesRegex(ValueError, "non-https"):
            cpw.fetch(URL)

    def test_redirect_handler_refuses_http_hop(self):
        # Checked per hop, so https -> http -> https cannot slip through on an
        # https final URL.
        handler = cpw._HttpsOnlyRedirect()
        req = urllib.request.Request(URL)
        with self.assertRaisesRegex(ValueError, "non-https"):
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example/x")
        nxt = handler.redirect_request(req, None, 302, "Found", {}, "https://objects.example/demo.plg")
        self.assertEqual(nxt.full_url, "https://objects.example/demo.plg")

    def test_opener_uses_the_https_only_handler(self):
        self.assertTrue(any(isinstance(h, cpw._HttpsOnlyRedirect) for h in cpw._OPENER.handlers))

    def test_oversized_body_refused(self):
        big = b"x" * (cpw.MAX_PLG_BYTES + 1)
        with mock.patch.object(cpw._OPENER, "open", return_value=FakeResponse(big)), self.assertRaisesRegex(ValueError, "larger than"):
            cpw.fetch(URL)

    def test_transient_404_is_retried(self):
        err = urllib.error.HTTPError(URL, 404, "Not Found", {}, None)
        with mock.patch.object(cpw._OPENER, "open", side_effect=[err, FakeResponse(b"<PLUGIN/>")]):
            self.assertEqual(cpw.fetch(URL, sleep=lambda s: None), b"<PLUGIN/>")

    def test_persistent_failure_raises_after_retries(self):
        err = urllib.error.HTTPError(URL, 503, "Unavailable", {}, None)
        with mock.patch.object(cpw._OPENER, "open", side_effect=[err] * 3) as urlopen:
            with self.assertRaises(urllib.error.HTTPError):
                cpw.fetch(URL, sleep=lambda s: None)
            self.assertEqual(urlopen.call_count, 3)

    def test_non_transient_error_is_not_retried(self):
        err = urllib.error.HTTPError(URL, 403, "Forbidden", {}, None)
        with mock.patch.object(cpw._OPENER, "open", side_effect=[err]) as urlopen:
            with self.assertRaises(urllib.error.HTTPError):
                cpw.fetch(URL, sleep=lambda s: None)
            self.assertEqual(urlopen.call_count, 1)


class MainTest(unittest.TestCase):
    """main()'s exit code IS the CI gate, so it is tested directly: a main()
    that printed errors but exited 0 would leave scheduled drift runs green."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "plugins").mkdir()
        (self.root / "ca_profile.xml").write_text("<RepositoryInfo><Profile>x</Profile></RepositoryInfo>")
        patcher = mock.patch.object(cpw, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, plg_text=None):
        fetch = mock.Mock(return_value=(plg_text or plg()).encode())
        with mock.patch.object(cpw, "fetch", fetch), contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cpw.main([])
        return rc, out.getvalue(), fetch

    def add_wrapper(self, text):
        (self.root / "plugins" / "demo.xml").write_text(text)

    def test_agreeing_pair_returns_0(self):
        self.add_wrapper(wrapper())
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 0, out)

    def test_drift_returns_1(self):
        self.add_wrapper(wrapper())
        rc, out, _ = self.run_main(plg(min="6.12.0"))
        self.assertEqual(rc, 1)
        self.assertIn("::error file=plugins/demo.xml::", out)

    def test_no_wrappers_returns_1(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc, _, _ = self.run_main()
        self.assertEqual(rc, 1)

    def test_malformed_wrapper_returns_1(self):
        self.add_wrapper("<Plugin>")
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 1)

    def test_bad_profile_returns_1(self):
        self.add_wrapper(wrapper())
        (self.root / "ca_profile.xml").write_text("<RepositoryInfo><Profile/></RepositoryInfo>")
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 1)

    def test_http_plugin_url_returns_1_without_fetching(self):
        self.add_wrapper(wrapper(PluginURL="http://example.com/demo.plg"))
        with mock.patch.object(cpw._OPENER, "open") as urlopen, contextlib.redirect_stdout(io.StringIO()):
            rc = cpw.main([])
        self.assertEqual(rc, 1)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
