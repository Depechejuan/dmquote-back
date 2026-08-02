# DMQuote backend

Django REST API and editorial administration for DMQuote.

## Local development

Copy `.env.example` to `.env`, then run:

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`, Django Admin at
`http://localhost:8000/admin/`, and OpenAPI documentation at
`http://localhost:8000/api/docs/`.

The DM Live importer accepts local exports only and contains no live network operation.

## Local DM Live imports

Imports read local MediaWiki XML exports or equivalent JSON files; they do not make
network requests:

```bash
python manage.py ingest_dmlive \
  --input /path/to/DM-Live-export.xml \
  --format auto \
  --dry-run
```

Run without `--dry-run` to persist the import. Use `--mark-missing` only when the
input is a complete source export; it marks absent pages as missing without deleting
their records. Raw page snapshots are written to the ignored `snapshots/` directory.
For a large export, add `--bulk` to use batched database writes.

JSON input accepts either a top-level list of pages or an object with a `pages` list.
Each page may contain `page_id`, `namespace`, `title`, and either top-level revision
fields or a `revision` object with `revision_id`, `timestamp`, and `text`.

Generate an editorial audit without changing records:

```bash
python manage.py audit_dmlive \
  --output reports/phase8-dmlive-audit.json
```

After the source owner has authorized publication, authorize the imported interview
text explicitly. This does not verify automatic song or album mentions:

```bash
python manage.py authorize_dmlive \
  --source-domain dmlive.wiki \
  --confirm
```
