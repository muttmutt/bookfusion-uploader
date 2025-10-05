#!/usr/bin/env -S uv run --python /Users/prscarr/.venvs/global/bin/python3
# BookFusion CLI uploader (no Calibre required)
# Flow: /uploads/init -> S3 POST -> /uploads/finalize (Rails-style metadata)
# Mirrors the Calibre plugin’s fields + digest computation.

import argparse, sys, os, json, hashlib, mimetypes
from pathlib import Path
import requests

API_BASE_DEFAULT = "https://www.bookfusion.com/calibre-api/v1"

def sha256_file(path, chunk=1024*1024):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def compute_calibre_metadata_digest(meta: dict, cover_path: str|None):
    """
    Matches the plugin's get_metadata_digest:
    concat these UTF-8 bytes in order (only if present):
      title, summary, language, isbn, issued_on,
      for each series: title, then index (as string) if not None,
      each author, each tag,
      each bookshelf (IF bookshelves is not None),
      cover: bytes(size) of 0x00, then a single 0x00 byte, then cover bytes.
    """
    h = hashlib.sha256()

    def upd(val):
        if val is None: return
        if isinstance(val, (bytes, bytearray)): h.update(bytes(val))
        else: h.update(str(val).encode("utf-8"))

    # Scalars
    upd(meta.get("title"))
    upd(meta.get("summary"))
    upd(meta.get("language"))
    upd(meta.get("isbn"))
    upd(meta.get("issued_on"))

    # Series
    for s in meta.get("series", []):
        upd(s.get("title"))
        idx = s.get("index")
        if idx is not None:
            upd(str(idx))

    # Authors, Tags
    for a in meta.get("author_list", []): upd(a)
    for t in meta.get("tag_list",   []): upd(t)

    # Bookshelves (omit entirely if None; include even if [] to match plugin semantics)
    shelves = meta.get("bookshelves", None)
    if shelves is not None:
        for sh in shelves:
            upd(sh)

    # Cover
    if cover_path:
        p = Path(cover_path)
        if p.is_file():
            size = p.stat().st_size
            h.update(bytes(size))      # N zero bytes
            h.update(b"\x00")
            with open(p, "rb") as f:
                while True:
                    b = f.read(65536)
                    if not b: break
                    h.update(b)

    return h.hexdigest()

def guess_mimetype(path: Path):
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"

def parse_args():
    ap = argparse.ArgumentParser(description="Upload a file to BookFusion like the Calibre plugin.")
    ap.add_argument("file", help="Path to book file (.pdf/.epub/.mobi/.azw3)")
    ap.add_argument("--api-key", help="BookFusion Calibre API key. If omitted, reads env BF_API_KEY or --api-key-file.")
    ap.add_argument("--api-key-file", help="File containing API key (first line).")
    ap.add_argument("--api-base", default=API_BASE_DEFAULT, help=f"API base (default: {API_BASE_DEFAULT})")
    # Metadata (all optional; server accepts sparse metadata)
    ap.add_argument("--title",   help="Title (default: filename stem)")
    ap.add_argument("--summary", help="Description/summary")
    ap.add_argument("--lang",    help="Language code (e.g., eng)")
    ap.add_argument("--isbn",    help="ISBN")
    ap.add_argument("--issued-on", help="Publication date YYYY-MM-DD")
    ap.add_argument("--series", action="append", metavar="TITLE[:INDEX]", help="Repeatable. Example: 'My Series:1' or 'My Series'")
    ap.add_argument("--author", action="append", dest="authors", help="Repeatable.")
    ap.add_argument("--tag",    action="append", dest="tags",    help="Repeatable.")
    ap.add_argument("--shelf",  action="append", dest="shelves", help="Repeatable. If any provided, bookshelves array is sent.")
    ap.add_argument("--cover",  help="Path to cover image to attach")
    ap.add_argument("-v","--verbose", action="store_true", help="Verbose logs")
    return ap.parse_args()

def load_api_key(args):
    if args.api_key: return args.api_key.strip()
    if args.api_key_file and Path(args.api_key_file).is_file():
        return Path(args.api_key_file).read_text().strip()
    env = os.environ.get("BF_API_KEY") or os.environ.get("API_KEY")
    if env: return env.strip()
    print("No API key. Use --api-key, --api-key-file, or set BF_API_KEY.", file=sys.stderr)
    sys.exit(2)

def do_init(api_base, auth, filename, file_digest, verbose=False):
    url = f"{api_base}/uploads/init"
    files = {"filename": (None, filename), "digest": (None, file_digest)}
    if verbose: print(f">>> INIT {url}")
    r = requests.post(url, files=files, auth=auth)
    if verbose: print(f"<<< {r.status_code} {r.reason}")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"init failed: HTTP {r.status_code} - {r.text[:500]}")
    data = r.json()
    if "url" not in data or "params" not in data: raise RuntimeError(f"init response missing fields: {data}")
    return data

def do_s3_post(s3_url, s3_params: dict, book_path: Path, verbose=False):
    # S3 expects all fields from params plus the file part
    fields = {k: str(v) for k, v in s3_params.items()}
    files = { **{k:(None,v) for k,v in fields.items()},
              "file": (book_path.name, open(book_path, "rb"), guess_mimetype(book_path)) }
    if verbose: print(f">>> S3 POST {s3_url}")
    r = requests.post(s3_url, files=files)
    if verbose: print(f"<<< {r.status_code} {r.reason}")
    if r.status_code != 204:
        raise RuntimeError(f"S3 upload failed: HTTP {r.status_code} - {r.text[:500]}")
    return True

def do_finalize(api_base, auth, s3_key, file_digest, meta: dict, meta_digest, cover_path=None, verbose=False):
    url = f"{api_base}/uploads/finalize"
    parts = []
    # Required fields
    parts.append(("key", (None, s3_key)))
    parts.append(("digest", (None, file_digest)))
    # Rails-style metadata
    parts.append(("metadata[calibre_metadata_digest]", (None, meta_digest)))
    parts.append(("metadata[title]", (None, meta["title"])))
    if meta.get("summary"):   parts.append(("metadata[summary]",  (None, meta["summary"])))
    if meta.get("language"):  parts.append(("metadata[language]", (None, meta["language"])))
    if meta.get("isbn"):      parts.append(("metadata[isbn]",     (None, meta["isbn"])))
    if meta.get("issued_on"): parts.append(("metadata[issued_on]",(None, meta["issued_on"])))
    for s in meta.get("series", []):
        parts.append(("metadata[series][][title]", (None, s["title"])))
        if s.get("index") is not None:
            parts.append(("metadata[series][][index]", (None, str(s["index"]))))
    for a in meta.get("author_list", []):
        parts.append(("metadata[author_list][]", (None, a)))
    for t in meta.get("tag_list", []):
        parts.append(("metadata[tag_list][]", (None, t)))
    shelves = meta.get("bookshelves", None)
    if shelves is not None:
        # Plugin sends an empty element first to force array semantics
        parts.append(("metadata[bookshelves][]", (None, "")))
        for sh in shelves:
            parts.append(("metadata[bookshelves][]", (None, sh)))
    if cover_path:
        cp = Path(cover_path)
        if cp.is_file():
            parts.append(("metadata[cover]", (cp.name, open(cp,"rb"), guess_mimetype(cp))))
    if verbose: print(f">>> FINALIZE {url}")
    r = requests.post(url, files=parts, auth=auth, headers={"Accept":"application/json"})
    if verbose:
        print(f"<<< {r.status_code} {r.reason}")
        rid = r.headers.get("x-request-id","")
        if rid: print(f"    X-Request-Id: {rid}")
    return r

def main():
    args = parse_args()
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    api_key = load_api_key(args)
    auth = (api_key, "")   # Basic api_key:

    title = args.title or path.stem
    meta = {
        "title": title,
        "summary": args.summary or None,
        "language": args.lang or None,
        "isbn": args.isbn or None,
        "issued_on": args.issued_on or None,
        "author_list": args.authors or [],
        "tag_list": (
           [t.strip() for tag in args.tags for t in tag.split(",")]
            if args.tags else []
        ),
        "series": []
    }
    if args.series:
        for item in args.series:
            if ":" in item:
                t, idx = item.split(":", 1)
                try:
                    idxv = float(idx) if "." in idx else int(idx)
                except:
                    idxv = idx
                meta["series"].append({"title": t, "index": idxv})
            else:
                meta["series"].append({"title": item, "index": None})

    # Only send bookshelves if user provided any
    meta["bookshelves"] = (args.shelves or None)
    cover_path = args.cover or None

    file_digest = sha256_file(path)
    if args.verbose:
        print(f">>> FILE: {path.name} size={path.stat().st_size} sha256={file_digest}")

    init = do_init(args.api_base, auth, path.name, file_digest, verbose=args.verbose)
    s3_url   = init["url"]
    s3_params= init["params"]
    s3_key   = s3_params.get("key")
    if args.verbose: print(f"    S3 key: {s3_key}")

    do_s3_post(s3_url, s3_params, path, verbose=args.verbose)

    meta_digest = compute_calibre_metadata_digest(meta, cover_path)
    if args.verbose: print(f"    metadata digest: {meta_digest}")

    r = do_finalize(args.api_base, auth, s3_key, file_digest, meta, meta_digest, cover_path, verbose=args.verbose)
    try:
        js = r.json()
    except Exception:
        js = None

    if r.status_code in (200,201) and js and "id" in js:
        print(json.dumps({"ok": True, "bookfusion_id": js["id"], "key": s3_key}, indent=2))
        sys.exit(0)
    else:
        print("Upload failed.", file=sys.stderr)
        print(f"HTTP {r.status_code}", file=sys.stderr)
        if js is not None:
            print(json.dumps(js, indent=2), file=sys.stderr)
        else:
            print(r.text[:1000], file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    sys.exit(main())
