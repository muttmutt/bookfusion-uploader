# 📚 BookFusion CLI Uploader (`bf_uploader.py`)

Upload your ebooks to [BookFusion](https://www.bookfusion.com) using their Calibre-style API — **no Calibre required**.

This Python script replicates the behavior of the Calibre plugin, including:
- S3-backed file upload
- Digest computation for metadata and file
- Finalization with Rails-style form submission

Works great for scripting, automation, and metadata-rich library management.

---

## 🚀 Features

- Upload `.epub`, `.mobi`, `.azw3`, `.pdf` files
- Supports full metadata (authors, tags, series, language, ISBN, cover image, shelves, etc.)
- Mimics Calibre’s plugin upload digest
- Supports API key from CLI, env var, or file
- Verbose output for debugging

---

## 🔧 Installation & Environment

Requires:
- Python 3.11+ (you’re using `uv` and a `venv`)
- `requests` module

Install dependencies into your global venv (or run via `uv`):
```bash
uv pip install requests