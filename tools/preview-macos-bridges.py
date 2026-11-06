#!/usr/bin/env python3
"""Preview MIME associations for the initial macOS application pilot."""
import json
import subprocess
import os
import fcntl
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Extensions both sides classify in the same family but read as different formats.
KNOWN_CONFLICTS = {
    "pcf": "macOS identifies Pkl source while Qt identifies Cisco VPN settings",
    "pic": "macOS identifies a PICT image while Qt identifies a Radiance HDR image",
    "vlc": "macOS identifies a VLC document while Qt identifies an MPEG playlist",
}
TYPES = {"txt": "text/plain", "py": "text/x-python", "json": "application/json",
         "pdf": "application/pdf", "mp4": "video/mp4"}


def build_associations(results, eligible=lambda app: True, types=TYPES):
    apps = {}
    for extension, mime in types.items():
        for app in results.get(extension, {}).get("applications", []):
            identifier = app["bundleID"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", identifier) or not eligible(app):
                continue
            entry = apps.setdefault(identifier, {"name": app["name"], "mimeTypes": set()})
            entry["mimeTypes"].add(mime)
    return {identifier: {"name": data["name"], "mimeTypes": sorted(data["mimeTypes"])}
            for identifier, data in sorted(apps.items())}


def is_installed_app(app):
    path = Path(app["path"])
    roots = (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications")
    return path.is_dir() and any(path.is_relative_to(root) for root in roots)


def discover_globs(text):
    extensions = {}
    unsupported = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(":")
        if len(fields) < 3:
            raise ValueError(f"Invalid MIME glob: {line}")
        weight, mime, pattern = fields[:3]
        if mime == "application/octet-stream":
            continue
        match = re.fullmatch(r"\*\.([A-Za-z0-9_+-]+)", pattern)
        if not match:
            unsupported.append({"mime": mime, "pattern": pattern})
            continue
        ext = match.group(1)
        extensions.setdefault(ext, []).append({"mime": mime, "weight": int(weight),
                                               "caseSensitive": len(fields) > 3 and fields[3] == "cs"})
    return extensions, unsupported


def query_qt_types(extensions, results=None):
    build = ROOT / "run/qt-mime-build"
    build.mkdir(parents=True, exist_ok=True)
    with (build / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cmake = ROOT / "CraftRoot/dev-utils/bin/cmake"
        subprocess.run([str(cmake), "-S", str(ROOT / "tests"), "-B", str(build),
                        f"-DCMAKE_PREFIX_PATH={ROOT / 'CraftRoot'}"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(cmake), "--build", str(build), "--target", "mime-file-check"],
                       check=True, stdout=subprocess.DEVNULL)
        names = ["sample." + ext for ext in sorted(extensions)]
        env = dict(os.environ, QT_DATA_DIRS=str(ROOT / "CraftRoot/share"))
        output = subprocess.run([str(build / "mime-file-check"), "--families", *names],
                                check=True, capture_output=True, text=True, env=env).stdout
        mac_names = sorted({value.get("preferredMIMEType") for value in (results or {}).values()
                            if value and value.get("preferredMIMEType")})
        names_output = subprocess.run([str(build / "mime-file-check"), "--names", *mac_names],
                                      check=True, capture_output=True, text=True, env=env).stdout if mac_names else ""
    canonical = dict(line.split("\t", 1) for line in names_output.splitlines())
    types = {name.removeprefix("sample."): {"mime": mime, "text": family == "text"}
             for name, mime, family in (line.split("\t") for line in output.splitlines())}
    for ext, value in (results or {}).items():
        if ext in types and value:
            types[ext]["macMime"] = canonical.get(value.get("preferredMIMEType"), "")
    return types


def make_report(globs, results, qt_types):
    extensions, unsupported = discover_globs(globs)
    report = {"matched": {}, "ambiguous": {}, "dynamic": {}, "unresolved": {}, "unsupportedPatterns": unsupported}
    for ext, candidates in sorted(extensions.items()):
        result = results.get(ext)
        mimes = sorted({candidate["mime"] for candidate in candidates})
        qt_info = qt_types.get(ext, {})
        qt_mime = qt_info.get("mime")
        record = {"mimeTypes": mimes, "candidates": candidates, "macOS": result, "qtMimeType": qt_mime}
        families = set(result.get("families", [])) if result else set()
        qt_family = "text" if qt_info.get("text") else (qt_mime.split("/", 1)[0] if qt_mime else "")
        if ext.lower() in KNOWN_CONFLICTS:
            record["reason"] = KNOWN_CONFLICTS[ext.lower()]
            category = "ambiguous"
        elif not result:
            category = "unresolved"
        elif result.get("isDynamic", True):
            category = "dynamic"
        elif not result.get("applications") or not qt_mime or qt_mime == "application/octet-stream" or qt_mime not in mimes:
            category = "unresolved"
        elif families and qt_family in {"text", "image", "audio", "video"} and qt_family not in families:
            category = "ambiguous"
        elif not families or qt_family not in {"text", "image", "audio", "video"}:
            if len({m.split("/", 1)[0] for m in mimes}) > 1:
                category = "ambiguous"
            elif not result.get("preferredMIMEType"):
                # No MIME from macOS is no evidence of a conflict; known
                # conflicts are listed in KNOWN_CONFLICTS.
                record["reason"] = "macOS declares no MIME type; accepted without a known conflict"
                category = "matched"
            elif (qt_info.get("macMime") or "").casefold() != qt_mime.casefold():
                record["reason"] = f"macOS MIME {result['preferredMIMEType']} differs from Qt MIME {qt_mime}"
                category = "unresolved"
            else:
                category = "matched"
        elif qt_info.get("macMime") and qt_info["macMime"].casefold() != qt_mime.casefold():
            # Same family, but Qt knows the macOS MIME as a different type
            # (.f4v: video/x-flv vs video/mp4): the apps would be offered for
            # every file of the Qt type. A macOS MIME unknown to Qt (.py:
            # text/x-python-script) cannot be verified as synonymous, but is
            # accepted by family compatibility as a coverage policy when no
            # conflict is known.
            record["reason"] = f"macOS MIME {result['preferredMIMEType']} is a different Qt type than {qt_mime}"
            category = "ambiguous"
        else:
            category = "matched"
        report[category][ext] = record
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-report", action="store_true", help="Report candidate associations without changing the installation")
    args = parser.parse_args()
    if args.full_report:
        globs = (ROOT / "CraftRoot/share/mime/globs2").read_text()
        extensions, _ = discover_globs(globs)
        result = subprocess.run(["swift", str(ROOT / "tools/query-macos-apps.swift"), *sorted(extensions)],
                                check=True, capture_output=True, text=True)
        results = json.loads(result.stdout)
        print(json.dumps(make_report(globs, results, query_qt_types(extensions, results)), ensure_ascii=False, indent=2))
        return
    result = subprocess.run(["swift", str(ROOT / "tools/query-macos-apps.swift"), *TYPES],
                            check=True, capture_output=True, text=True)
    print(json.dumps(build_associations(json.loads(result.stdout), is_installed_app), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
