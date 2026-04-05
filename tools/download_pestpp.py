import json
import os
import sys
import urllib.request
import zipfile


def _download(url, dst_path):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    urllib.request.urlretrieve(url, dst_path)


def main():
    api = "https://api.github.com/repos/usgs/pestpp/releases/latest"
    req = urllib.request.Request(api, headers={"User-Agent": "Tomato_Cal"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rel = json.load(r)

    assets = rel.get("assets") or []
    if not assets:
        raise SystemExit("No assets found in latest release")

    candidates = []
    for a in assets:
        name = (a.get("name") or "").strip()
        url = (a.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        name_l = name.lower()
        score = 0
        if name_l.endswith(".zip"):
            score += 5
        if "win" in name_l or "windows" in name_l:
            score += 10
        if "pestpp" in name_l:
            score += 3
        candidates.append((score, name, url))

    if not candidates:
        raise SystemExit("No downloadable assets found")

    candidates.sort(reverse=True)
    _, name, url = candidates[0]

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dst_dir = os.path.join(root, "pestpp")
    os.makedirs(dst_dir, exist_ok=True)

    zip_path = os.path.join(dst_dir, name)
    if not os.path.exists(zip_path):
        print(f"Downloading {url}")
        print(f" -> {zip_path}")
        _download(url, zip_path)
    else:
        print(f"Zip exists: {zip_path}")

    extract_dir = os.path.join(dst_dir, "dist")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)

    ies = None
    for base, _, files in os.walk(extract_dir):
        for fn in files:
            if fn.lower() == "pestpp-ies.exe":
                ies = os.path.join(base, fn)
                break
        if ies:
            break

    if not ies:
        raise SystemExit("pestpp-ies.exe not found after extraction")

    print(f"pestpp-ies.exe: {ies}")
    print("OK")


if __name__ == "__main__":
    main()
