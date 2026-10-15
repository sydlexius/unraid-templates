#!/usr/bin/env python3
"""Detects drift between each plugins/*.xml wrapper and the .plg it points at.

A Community Applications plugin listing is two files in two repositories: the
wrapper here, and the .plg published by the plugin's own repo. Nothing else can
see them drift apart, so this fetches the .plg named by each wrapper's
<PluginURL> and checks the two agree. Ported from watch-aware-preloader's
test/ca_wrapper_test.sh, which did the same check when both files lived in one
repository.

The load-bearing assertion is PluginURL: CA matches the wrapper's <PluginURL>
against the .plg's own pluginURL attribute EXACTLY, and that pairing is the
plugin's identity key. A mismatch is the one hard failure mode of a submission.

The other fields are checked for AGREEMENT, and the precedence differs by field
(the .plg overrides support/min/max, but CA publishes the wrapper's IconFA), so
the only safe state is agreement: a wrapper that disagrees with the shipped .plg
describes a plugin that does not exist.

Usage: check_plugin_wrappers.py [WRAPPER ...]   (default: plugins/*.xml)
"""

import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# CA rejects a submission missing any of these: the starter's "Required fields"
# block is exactly these four.
CA_REQUIRED = ("Name", "Overview", "PluginURL", "PluginAuthor")

# Optional to CA, but a listing without a support link, project link or category
# is worse for a user reading the catalog. Reported separately so the message
# does not claim CA rejects it.
REPO_CONVENTION = ("Support", "Project", "Category")

# (.plg attribute, wrapper element) pairs checked for agreement.
AGREEMENT = (("support", "Support"), ("min", "MinVer"), ("max", "MaxVer"), ("icon", "IconFA"))

FETCH_TIMEOUT = 30

# A real .plg is a few KiB; anything near this is not one, and reading it whole
# would let a hostile host hold the runner.
MAX_PLG_BYTES = 1 << 20

# Transient failures retried before a run goes red. 404 is included because a
# release's latest/download URL 404s in the window between the release being
# published and its .plg asset finishing upload.
RETRY_DELAYS = (5, 20)
RETRY_STATUSES = {404, 429, 500, 502, 503, 504}


def _fetch_once(url):
    req = urllib.request.Request(url, headers={"User-Agent": "unraid-templates-drift-check"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        # urllib follows redirects to plain http, so the https check has to be
        # made on where the request ENDED, not only where it started.
        if not resp.geturl().startswith("https://"):
            raise ValueError(f"PluginURL redirected to non-https {resp.geturl()}")
        body = resp.read(MAX_PLG_BYTES + 1)
    if len(body) > MAX_PLG_BYTES:
        raise ValueError(f".plg is larger than {MAX_PLG_BYTES} bytes; refusing to parse it")
    return body


def fetch(url, sleep=time.sleep):
    if not url.startswith("https://"):
        raise ValueError(f"refusing to fetch non-https PluginURL: {url}")
    for delay in (*RETRY_DELAYS, None):
        try:
            return _fetch_once(url)
        except urllib.error.HTTPError as exc:
            if delay is None or exc.code not in RETRY_STATUSES:
                raise
        except urllib.error.URLError:
            if delay is None:
                raise
        sleep(delay)


def check(wrapper_xml, plg_xml):
    """Return a list of failure messages for one wrapper/.plg pair (empty = ok).

    Both arguments are XML text. Parsing the .plg as XML rather than searching
    it as text matters: .plg files document their own attributes in comments
    (watch-aware-preloader's quotes icon="hdd-o" above the real attribute), and
    the original text-search version of this check compared the wrapper against
    a sentence in one of them.
    """
    root = ET.fromstring(wrapper_xml)
    if root.tag != "Plugin":
        return [f"wrapper root is <{root.tag}>, want <Plugin>"]

    def field(name):
        return (root.findtext(name) or "").strip()

    errors = []
    errors += [f"missing a non-empty <{f}> (required by CA)" for f in CA_REQUIRED if not field(f)]
    errors += [f"missing a non-empty <{f}> (repo convention)" for f in REPO_CONVENTION if not field(f)]
    if errors:
        return errors

    plg = ET.fromstring(plg_xml)
    if plg.tag != "PLUGIN":
        return [f".plg root is <{plg.tag}>, want <PLUGIN>"]

    # NOT field(): that strips whitespace, and this comparison is byte-exact.
    plg_url, wrap_url = plg.get("pluginURL"), root.findtext("PluginURL")
    if plg_url is None:
        errors.append(".plg has no pluginURL= attribute to compare against")
    elif plg_url != wrap_url:
        errors.append(
            "<PluginURL> does not match the .plg's pluginURL exactly.\n"
            f"    .plg:    {plg_url}\n"
            f"    wrapper: {wrap_url}\n"
            "    CA matches these byte-for-byte; a mismatch fails the submission."
        )

    for plg_attr, wrap_field in AGREEMENT:
        wrap_val, plg_val = field(wrap_field), plg.get(plg_attr)
        # An attribute only one side carries cannot conflict. For min/max the
        # wrapper value is then the one CA uses.
        if not wrap_val or plg_val is None:
            continue
        if plg_attr == "support":
            # support= may be the repo root while the wrapper names /issues: the
            # .plg wins either way, and /issues is the convention CA listings
            # use. Compare on PATH BOUNDARIES, not a raw prefix, or
            # ".../issues.evil.example/x" would pass as beneath ".../issues".
            base = plg_val.rstrip("/")
            if wrap_val != base and not wrap_val.startswith(base + "/"):
                errors.append(f"<Support> {wrap_val} is not the .plg's support= {plg_val} nor a path beneath it")
        elif plg_attr == "icon":
            # The fa- prefix is spelling, not identity: the MOTD plugin ships
            # icon="fa-desktop" in its .plg and <IconFA>desktop</IconFA> in its
            # wrapper, which name the same icon.
            if plg_val.removeprefix("fa-") != wrap_val.removeprefix("fa-"):
                errors.append(f"<IconFA> is {wrap_val} but the .plg's icon= is {plg_val}")
        elif plg_val != wrap_val:
            errors.append(f"<{wrap_field}> is {wrap_val} but the .plg's {plg_attr}= is {plg_val}")
    return errors


def check_profile(profile_xml):
    """Return failure messages for ca_profile.xml (empty = ok).

    An empty <Profile> blocks a CA submission from finalizing. Either root
    spelling is accepted: this repo keeps <RepositoryInfo>, the starter uses
    <CommunityApplications>, and CA accepts both.
    """
    root = ET.fromstring(profile_xml)
    if root.tag not in ("RepositoryInfo", "CommunityApplications"):
        return [f"ca_profile.xml root is <{root.tag}>, want <RepositoryInfo> or <CommunityApplications>"]
    if not (root.findtext("Profile") or "").strip():
        return ["ca_profile.xml <Profile> is empty; CA blocks submission on this"]
    return []


def report(path, errors):
    try:
        path = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass  # outside the repo (a path given on the command line): keep it as is
    for err in errors:
        # ::error is a GitHub Actions annotation (plain text elsewhere), which
        # needs its newlines escaped to stay one annotation.
        print(f"::error file={path}::" + err.replace("\n", "%0A"))
    if not errors:
        print(f"ok: {path}")


def main(argv):
    paths = [Path(p) for p in argv] or sorted((REPO_ROOT / "plugins").glob("*.xml"))
    # Fail loudly on an empty set rather than passing having checked nothing.
    if not paths:
        print("FAIL: no plugin wrappers found under plugins/", file=sys.stderr)
        return 1

    rc = 0
    profile = REPO_ROOT / "ca_profile.xml"
    try:
        errors = check_profile(profile.read_bytes())
    except Exception as exc:  # noqa: BLE001 - reported like any other failure
        errors = [f"{type(exc).__name__}: {exc}"]
    report(profile, errors)
    rc |= bool(errors)

    for path in paths:
        try:
            wrapper_xml = path.read_bytes()
            url = (ET.fromstring(wrapper_xml).findtext("PluginURL") or "").strip()
            # No URL means check() fails on the required fields before it ever
            # parses the .plg, so there is nothing to fetch.
            errors = check(wrapper_xml, fetch(url) if url else None)
        except Exception as exc:  # noqa: BLE001 - every failure is reported per file
            errors = [f"{type(exc).__name__}: {exc}"]
        report(path, errors)
        rc |= bool(errors)
    return int(rc)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
