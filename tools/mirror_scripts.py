#!/usr/bin/env python3
"""Mirror runtime resources referenced by lpx plugins into scripts/.

Downloads each script(), script-path, jq_file, and mock_file URL (plus kelee.one
Resource/Zip files injected by a plugin). Icons are ignored. kelee.one is tried
with a Loon User-Agent, then public GitHub copies of the same filename.

Rewrites a URL inside .lpx files only after the download validates. Refreshes
manifest.json hashes for plugins whose bytes changed. Does not schedule anything.

Usage:
  python3 tools/mirror_scripts.py
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LPX_DIR = ROOT / "lpx"
SCRIPTS_DIR = ROOT / "scripts"
MANIFEST_PATH = ROOT / "manifest.json"
SCRIPT_MANIFEST_PATH = SCRIPTS_DIR / "manifest.json"
MIRROR_BASE = "https://raw.githubusercontent.com/zijinan/star-loon/main/scripts/"
LOON_UA = "Loon/3.2.4 (iPhone; iOS 18)"
BROWSER_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"
MAX_BYTES = 25 * 1024 * 1024

# Public copies used when kelee.one returns a Cloudflare challenge.
# Keys are the original kelee.one URLs. Order is the try order.
KELEE_FALLBACKS = {
    "https://kelee.one/Resource/JavaScript/Bilibili/Bilibili_json_kokoryh.js": [
        "https://raw.githubusercontent.com/zmjde/loon-plugins/main/JS/Bilibili/Bilibili_json_kokoryh.js",
    ],
    "https://kelee.one/Resource/JavaScript/YouTube/YouTube_remove_ads/YouTube_remove_ads_request.js": [
        "https://raw.githubusercontent.com/zmjde/loon-plugins/main/JS/YouTube/YouTube_remove_ads/YouTube_remove_ads_request.js",
    ],
    "https://kelee.one/Resource/JavaScript/YouTube/YouTube_remove_ads/YouTube_remove_ads_response.js": [
        "https://raw.githubusercontent.com/zmjde/loon-plugins/main/JS/YouTube/YouTube_remove_ads/YouTube_remove_ads_response.js",
    ],
    "https://kelee.one/Resource/JQLang/Amap/search_poi_detail.jq": [
        "https://raw.githubusercontent.com/zmjde/loon-plugins/main/JQ/Amap/search_poi_detail.jq",
    ],
    "https://kelee.one/Resource/JQLang/Amap/updatable.jq": [
        "https://raw.githubusercontent.com/zmjde/loon-plugins/main/JQ/Amap/updatable.jq",
    ],
    "https://kelee.one/Resource/Zip/DREAME/d6996fee95380affdf740ee44a85fbe9___UNI__EDB922E.zip": [
        "https://raw.githubusercontent.com/luestr/ProxyResource/main/Resource/Zip/DREAME/d6996fee95380affdf740ee44a85fbe9___UNI__EDB922E.zip",
    ],
}

# Romeo saved these under kelee.one_<filename> because KeleeOne does not have them.
ROMEO = "https://raw.githubusercontent.com/ifflagged/Romeo/main/Modules/JavaScript/Kelee"
for _path, _folder, _file in [
    ("/Resource/JavaScript/Bixin/common_tab.js", "Bixin_remove_ads", "kelee.one_common_tab.js"),
    ("/Resource/JavaScript/Bixin/my_page.js", "Bixin_remove_ads", "kelee.one_my_page.js"),
    ("/Resource/JavaScript/Chelaile/Chelaile_remove_ads.js", "Chelaile_remove_ads", "kelee.one_Chelaile_remove_ads.js"),
    ("/Resource/JavaScript/DjDuoDuo/DjDuoDuo_remove_ads.js", "DjDuoDuo_remove_ads", "kelee.one_DjDuoDuo_remove_ads.js"),
    ("/Resource/JavaScript/IPATool/AppStoreAPI.js", "IPATool", "kelee.one_AppStoreAPI.js"),
    ("/Resource/JavaScript/IPATool/Installer.js", "IPATool", "kelee.one_Installer.js"),
    ("/Resource/JavaScript/MotorFans/MotorFans_remove_ads.js", "MotorFans_remove_ads", "kelee.one_MotorFans_remove_ads.js"),
    ("/Resource/JavaScript/Qbb/homepage.js", "Qbb_remove_ads", "kelee.one_homepage.js"),
    ("/Resource/JavaScript/Qbb/my.js", "Qbb_remove_ads", "kelee.one_my.js"),
    ("/Resource/JavaScript/ShoujiDesk/base_init.js", "ShoujiDesk_remove_ads", "kelee.one_base_init.js"),
    ("/Resource/JavaScript/TestFlight/AutoJoinTF.js", "Auto_Join_TF", "kelee.one_AutoJoinTF.js"),
    ("/Resource/JavaScript/TestFlight/AutoMonitorTF.js", "Auto_Join_TF", "kelee.one_AutoMonitorTF.js"),
    ("/Resource/JavaScript/TestFlight/CaptureAccountToken.js", "Auto_Join_TF", "kelee.one_CaptureAccountToken.js"),
    ("/Resource/JavaScript/Weidian/getAppConfig.js", "Weidian_remove_ads", "kelee.one_getAppConfig.js"),
    ("/Resource/JavaScript/Weidian/wallet.js", "Weidian_remove_ads", "kelee.one_wallet.js"),
    ("/Resource/JavaScript/XiaojukejiCharge/XiaojukejiCharge_remove_ads.js", "XiaojukejiCharge_remove_ads", "kelee.one_XiaojukejiCharge_remove_ads.js"),
    ("/Resource/JavaScript/iWallBiZhi/core_initialize.js", "iWallBiZhi_remove_ads", "kelee.one_core_initialize.js"),
    ("/Resource/JavaScript/iWallBiZhi/landing.js", "iWallBiZhi_remove_ads", "kelee.one_landing.js"),
    ("/Resource/JavaScript/iWallBiZhi/landing_initialize.js", "iWallBiZhi_remove_ads", "kelee.one_landing_initialize.js"),
]:
    KELEE_FALLBACKS.setdefault("https://kelee.one" + _path, []).append(f"{ROMEO}/{_folder}/{_file}")

# GitLab raw for this path currently 404s. A few public mirrors are tried and rejected if invalid.
OTHER_FALLBACKS = {
    "https://gitlab.com/lodepuly/vpn_tool/-/raw/master/Resource/Script/TikTok/TikTok_remove_watermark.js": [
        "https://raw.githubusercontent.com/lodepuly/vpn_tool/master/Resource/Script/TikTok/TikTok_remove_watermark.js",
        "https://cdn.jsdelivr.net/gh/lodepuly/vpn_tool@master/Resource/Script/TikTok/TikTok_remove_watermark.js",
    ],
}

EXTRACTORS = [
    ("script", re.compile(r'script\(\s*"(https?://[^"]+)"')),
    ("script-path", re.compile(r"script-path\s*=\s*(https?://[^\s,]+)")),
    ("jq_file", re.compile(r'jq_file\(\s*"(https?://[^"]+)"')),
    ("mock_file", re.compile(r'mock_file\(\s*"(?:text|json)"\s*,\s*"(https?://[^"]+)"')),
    ("zip", re.compile(r"https?://kelee\.one/Resource/Zip/[^\"\s\\]+")),
]

def extract_urls() -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(LPX_DIR.glob("*.lpx")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for kind, rx in EXTRACTORS:
            for match in rx.finditer(text):
                url = match.group(0) if kind == "zip" else match.group(1)
                url = url.rstrip("\\")
                if "zijinan/star-loon" in url:
                    continue
                if "/IconResource/" in url or urlparse(url).path.endswith((".png", ".jpg", ".webp")):
                    continue
                found[url].add(kind if kind != "zip" else "zip")
    return found


def mirror_rel(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path.startswith("/"):
        raise ValueError(f"unsupported url {url}")
    parts = [parsed.netloc] + [p for p in parsed.path.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValueError(f"unsafe path {url}")
    rel = Path("scripts").joinpath(*parts)
    if parsed.query:
        rel = rel.with_name(rel.name + "__" + hashlib.sha256(parsed.query.encode()).hexdigest()[:8])
    return rel


def candidates_for(url: str) -> list[tuple[str, str]]:
    """(fetch_url, note) in try order. The original URL is always first."""
    out = [(url, "original")]
    name = urlparse(url).path.rsplit("/", 1)[-1]
    if url.startswith("https://kelee.one/Resource/"):
        if name.endswith(".js"):
            out.append((
                f"https://raw.githubusercontent.com/mihoyo-typ/KeleeOne/Loon/Script/{name}",
                "kelee.one blocked; same filename in mihoyo-typ/KeleeOne",
            ))
        elif name.endswith(".jq"):
            out.append((
                f"https://raw.githubusercontent.com/mihoyo-typ/KeleeOne/Loon/JQLang/{name}",
                "kelee.one blocked; same filename in mihoyo-typ/KeleeOne",
            ))
        for alt in KELEE_FALLBACKS.get(url, []):
            out.append((alt, "kelee.one blocked; public GitHub copy of this file"))
    for alt in OTHER_FALLBACKS.get(url, []):
        out.append((alt, "original host unreachable; tried public mirror"))
    # de-dupe while keeping order
    seen = set()
    unique = []
    for item in out:
        if item[0] in seen:
            continue
        seen.add(item[0])
        unique.append(item)
    return unique


def fetch(url: str) -> tuple[bytes | None, str | None]:
    errors = []
    for ua in (LOON_UA, BROWSER_UA):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()) as resp:
                data = resp.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    return None, f"larger than {MAX_BYTES} bytes"
                return data, None
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code} ua={ua.split('/', 1)[0]}")
            if exc.code not in {403, 429, 503}:
                break
        except Exception as exc:  # noqa: BLE001 - report the network failure
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    return None, "; ".join(errors)


def validate(data: bytes, original_url: str) -> str | None:
    if not data:
        return "empty body"
    head = data[:800].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html") or b"cf-challenge" in head or b"just a moment" in head:
        return "HTML or Cloudflare challenge page"
    if b"<title>just a moment" in head or b"attention required" in head:
        return "Cloudflare challenge page"
    path = urlparse(original_url).path.lower()
    if path.endswith(".js"):
        sample = data[:4000]
        markers = (b"function", b"const ", b"let ", b"var ", b"=>", b"class ", b"import ", b"exports", b"(()", b"!function", b"(function")
        if not any(m in data for m in markers) and not sample.strip().startswith((b"/*", b"//", b"'use", b'"use')):
            return "body does not look like JavaScript"
    elif path.endswith(".json"):
        try:
            json.loads(data.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return f"invalid JSON ({exc})"
    elif path.endswith(".jq"):
        if b"<" in data[:1]:
            return "jq file looks like markup"
    elif path.endswith(".zip"):
        if not data.startswith(b"PK"):
            return "not a zip archive"
        expect = "e0cc9cb77d9e0cf275e41e73dba3f988"
        if "d6996fee95380affdf740ee44a85fbe9" in original_url:
            digest = hashlib.md5(data).hexdigest()
            if digest != expect:
                return f"zip md5 {digest} != {expect} hardcoded by the plugin"
    return None


def human_size(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def remote_loads(data: bytes, original_url: str) -> list[str]:
    """Flag scripts that still fetch or emit other remote JavaScript.

    Citation comments (引用地址 / 引用链接) are ignored. eval() of a local
    string, and TypeScript JSDoc import("./file"), are not treated as a
    remote load.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"(^|\s)//.*?$", "", code, flags=re.M)
    hits = []
    urls = sorted(set(re.findall(r"https?://[^\"'\s)]+\.js\b", code)))
    urls = [u for u in urls if u != original_url and "zijinan/star-loon" not in u]
    if urls:
        hits.append("remote script URL: " + ", ".join(urls[:12]))
    if re.search(r"(?:\$\s*\.\s*getScript|\.getScript\s*\(|getScript\s*`)", code):
        hits.append("getScript")
    if re.search(r"importScripts\s*\(", code):
        hits.append("importScripts")
    if re.search(r"\bimport\s*\(\s*['\"]https?:", code) or re.search(r"\bimport\s*\(\s*[A-Za-z_]", code):
        hits.append("dynamic import()")
    return hits


def load_previous() -> dict[str, dict]:
    if not SCRIPT_MANIFEST_PATH.exists():
        return {}
    data = json.loads(SCRIPT_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {item["original_url"]: item for item in data.get("files", [])}


def main() -> None:
    found = extract_urls()
    previous = load_previous()
    for url, item in previous.items():
        found.setdefault(url, set()).update(item.get("kinds") or [])
    print(f"unique resource URLs: {len(found)}")

    def work(url: str):
        rel = mirror_rel(url)
        attempts = []
        for fetch_url, note in candidates_for(url):
            data, err = fetch(fetch_url)
            if err:
                attempts.append(f"{fetch_url} -> {err}")
                continue
            problem = validate(data, url)
            if problem:
                attempts.append(f"{fetch_url} -> {problem}")
                continue
            return {
                "ok": True,
                "original_url": url,
                "fetched_from": fetch_url,
                "note": note,
                "rel": rel,
                "data": data,
                "kinds": sorted(found[url]),
                "reason": None,
            }
        kept = previous.get(url)
        kept_path = ROOT / rel
        if kept and kept_path.is_file():
            return {
                "ok": True,
                "original_url": url,
                "fetched_from": kept.get("fetched_from", url),
                "note": (kept.get("note") or "") + " Refresh failed; kept the previous copy.",
                "rel": rel,
                "data": kept_path.read_bytes(),
                "kinds": sorted(found[url]),
                "reason": " | ".join(attempts)[:800],
            }
        return {
            "ok": False,
            "original_url": url,
            "rel": rel,
            "kinds": sorted(found[url]),
            "reason": " | ".join(attempts)[:800],
        }

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(work, url) for url in sorted(found)]
        for i, fut in enumerate(as_completed(futures), 1):
            item = fut.result()
            results.append(item)
            state = "ok" if item["ok"] else "FAIL"
            print(f"[{i}/{len(found)}] {state} {item['original_url'][:110]}")

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    url_to_mirror = {}
    manifest_files = []
    remote = []
    for item in sorted(ok, key=lambda r: r["original_url"]):
        dest = ROOT / item["rel"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(item["data"])
        mirror_url = MIRROR_BASE + "/".join(item["rel"].parts[1:])
        url_to_mirror[item["original_url"]] = mirror_url
        loads = remote_loads(item["data"], item["original_url"])
        entry = {
            "original_url": item["original_url"],
            "mirror_path": item["rel"].as_posix(),
            "mirror_url": mirror_url,
            "fetched_from": item["fetched_from"],
            "note": item["note"],
            "kinds": item["kinds"],
            "sha256": hashlib.sha256(item["data"]).hexdigest(),
            "size": len(item["data"]),
        }
        if loads:
            entry["remote_loads"] = loads
            remote.append(entry)
        manifest_files.append(entry)

    # Rewrite only successful URLs. Longest first so one URL cannot eat another.
    replaced_plugins = []
    for path in sorted(LPX_DIR.glob("*.lpx")):
        text = path.read_text(encoding="utf-8", errors="replace")
        new = text
        for original in sorted(url_to_mirror, key=len, reverse=True):
            new = new.replace(original, url_to_mirror[original])
        if new != text:
            path.write_text(new, encoding="utf-8")
            replaced_plugins.append(path.name)

    plugin_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for name in replaced_plugins:
        data = (LPX_DIR / name).read_bytes()
        meta = plugin_manifest["plugins"][name]
        meta["sha256_12"] = hashlib.sha256(data).hexdigest()[:12]
        meta["size"] = len(data)
        meta["size_human"] = human_size(len(data))
    plugin_manifest["count"] = len(plugin_manifest["plugins"])
    MANIFEST_PATH.write_text(json.dumps(plugin_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    script_manifest = {
        "mirror_base": MIRROR_BASE,
        "count_mirrored": len(manifest_files),
        "count_left_external": len(bad),
        "plugins_rewritten": len(replaced_plugins),
        "files": manifest_files,
        "left_external": [
            {
                "original_url": item["original_url"],
                "kinds": item["kinds"],
                "reason": item["reason"],
            }
            for item in sorted(bad, key=lambda r: r["original_url"])
        ],
        "remote_code_dependencies": [
            {
                "mirror_path": item["mirror_path"],
                "original_url": item["original_url"],
                "remote_loads": item["remote_loads"],
            }
            for item in remote
        ],
    }
    SCRIPT_MANIFEST_PATH.write_text(json.dumps(script_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"mirrored {len(ok)} left external {len(bad)} plugins rewritten {len(replaced_plugins)} remote-load files {len(remote)}")


if __name__ == "__main__":
    main()
