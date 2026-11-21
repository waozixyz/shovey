#!/usr/bin/env python3
"""Fetch an exact local Android build from this repository's LFS storage."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BATCH = "https://git.waozi.xyz/waozi/shovey.git/info/lfs/objects/batch"
LIMIT = 128 * 1024 * 1024


def checked_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "git.waozi.xyz"
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError("Repair download must stay on the canonical Git host")
    return url


class CanonicalRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(digest, size, output, open_url=None):
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not 0 < size <= LIMIT:
        raise ValueError("Invalid repair digest or size")
    if open_url is None:
        open_url = build_opener(CanonicalRedirect()).open
    payload = json.dumps({"operation": "download", "transfers": ["basic"],
                          "objects": [{"oid": digest, "size": size}]}).encode()
    request = Request(BATCH, data=payload, headers={
        "Content-Type": "application/vnd.git-lfs+json",
        "Accept": "application/vnd.git-lfs+json"})
    with open_url(request, timeout=60) as response:
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Oversized LFS response")
    objects = json.loads(body)["objects"]
    if len(objects) != 1 or objects[0].get("oid") != digest or objects[0].get("size") != size:
        raise ValueError("LFS returned a different object")
    action = objects[0]["actions"]["download"]
    headers = action.get("header", {})
    if not isinstance(headers, dict) or any(key.lower() != "authorization" for key in headers):
        raise ValueError("Unexpected LFS download headers")
    request = Request(checked_url(action["href"]), headers=headers)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".download")
    created = False
    try:
        with partial.open("xb") as target:
            created = True
            checksum = hashlib.sha256()
            count = 0
            with open_url(request, timeout=60) as response:
                while chunk := response.read(65536):
                    count += len(chunk)
                    if count > size:
                        raise ValueError("Repair download exceeds declared size")
                    checksum.update(chunk)
                    target.write(chunk)
            if count != size or checksum.hexdigest() != digest:
                raise ValueError("Repair download does not match the local build")
        partial.replace(output)
    finally:
        if created:
            partial.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    fetch(args.sha256, args.size, args.output)
    print("Exact local APK downloaded and verified")
