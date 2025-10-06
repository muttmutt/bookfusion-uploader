# 📚 `bf_uploader.py` – Full Step-by-Step Walkthrough

This document explains how the `bf_uploader.py` script works, line by line.  
It covers every function and the overall flow from parsing command-line arguments to uploading a book and its metadata to BookFusion.

---

## 1. 🏗 Imports and Constants

```python
import argparse, sys, os, json, hashlib, mimetypes
from pathlib import Path
import requests

API_BASE_DEFAULT = "https://www.bookfusion.com/calibre-api/v1"
```

- Standard libraries for CLI, file handling, hashing, and MIME detection
- `requests` for HTTP requests
- `API_BASE_DEFAULT` is the Calibre-compatible BookFusion endpoint

---

## 2. 🔑 File Hashing – `sha256_file()`

```python
def sha256_file(path, chunk=1024*1024):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()
```

Computes a SHA-256 digest of the file in chunks.  
Used in both `/uploads/init` and `/uploads/finalize`.

---

## 3. 🧬 Metadata Digest – `compute_calibre_metadata_digest()`

```python
def compute_calibre_metadata_digest(meta: dict, cover_path: str|None):
```

Creates a digest of metadata that matches Calibre plugin behavior:

- Hashes: title, summary, language, ISBN, issued date
- Iterates over:
  - series (title + index)
  - authors
  - tags
  - bookshelves (if not `None`)
- If a cover is provided:
  - Adds zero bytes (based on size), a null byte, and cover data

Returns the SHA-256 hash of this structure.

---

## 4. 📎 MIME Guessing – `guess_mimetype()`

```python
def guess_mimetype(path: Path):
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"
```

Determines MIME type of a file based on its extension.

---

## 5. 🧾 CLI Argument Parsing – `parse_args()`

```python
def parse_args():
    ...
```

Defines the command-line interface:

- Required: book file path
- Optional: `--title`, `--summary`, `--lang`, `--isbn`, `--issued-on`
- Repeatable: `--author`, `--tag`, `--series`, `--shelf`
- `--cover` for image attachment
- API key options: `--api-key`, `--api-key-file`, or `BF_API_KEY`/`API_KEY` env vars
- `--verbose` for logging

---

## 6. 🔐 API Key Loader – `load_api_key()`

```python
def load_api_key(args):
```

Loads API key using:

1. `--api-key`
2. File path via `--api-key-file`
3. Environment variables

Fails if none provided.

---

## 7. 🛰️ Upload Initialization – `do_init()`

```python
def do_init(api_base, auth, filename, file_digest, verbose=False):
```

Calls `/uploads/init` with filename and SHA-256 digest.  
Returns pre-signed S3 upload URL and POST parameters.

---

## 8. ☁️ Upload to S3 – `do_s3_post()`

```python
def do_s3_post(s3_url, s3_params, book_path, verbose=False):
```

Posts the file and required fields to the provided S3 URL.  
Expects HTTP 204 on success.

---

## 9. ✅ Finalize Upload – `do_finalize()`

```python
def do_finalize(api_base, auth, s3_key, file_digest, meta, meta_digest, cover_path=None, verbose=False):
```

Finalizes the upload by POSTing:

- S3 key and file hash
- Metadata fields in Rails-style
- Cover (if present)
- Metadata digest

Returns the HTTP response.

---

## 10. 🧠 Main Function – `main()`

```python
def main():
```

1. Parses args
2. Validates file
3. Loads API key
4. Builds metadata dict
5. Computes file digest
6. Calls `do_init()`
7. Uploads file via `do_s3_post()`
8. Computes metadata digest
9. Calls `do_finalize()`
10. Outputs success or error

---

## 11. 🚀 Script Entry Point

```python
if __name__ == "__main__":
    sys.exit(main())
```

Triggers the `main()` function when run directly.
