# DMQuote backend

Django REST API and editorial administration for DMQuote.

## Local development

Copy `.env.example` to `.env`, then run:

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`, Django Admin at
`http://localhost:8000/dmlog/`, and OpenAPI documentation at
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

## Local deployment

The Compose backend forces `DATABASE_URL` to the local `db` service, even if the
ignored `.env` file contains a production Neon URL. It also runs migrations and
the configured local superuser command at startup:

```bash
docker compose up --build -d
docker compose ps
```

To load a local XML export, place it under the ignored `local-imports/` directory
and run:

```bash
docker compose exec backend python manage.py seed_catalog \
  --input apps/catalog/data/depeche_mode_catalog_v1.json
docker compose exec backend python manage.py ingest_dmlive \
  --input local-imports/DM+Live-export.xml \
  --format auto --bulk --mark-missing
docker compose exec backend python manage.py scan_mentions
docker compose exec backend python manage.py authorize_dmlive \
  --source-domain dmlive.wiki --confirm
```

The versioned catalogue contains one canonical record per song. Songs belonging
to an album are listed inside that album, while official songs without a
primary album are listed in `standalone_songs`. Re-running `seed_catalog` is
safe and reports existing database records that are not present in the
catalogue for manual review; it does not delete them automatically.

The backend is available at `http://localhost:8000`, Admin at
`http://localhost:8000/dmlog/`, and the frontend at `http://localhost:5173`.

## Vercel deployment

The backend is prepared as a Vercel Python Function through `api/index.py` and
`vercel.json`. Create or link the Vercel project with the name `dmquote-back`,
using the repository root as its project root. The project must define these
runtime variables in Vercel; values are not stored in Git:

```text
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=<long-random-production-secret>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=dmquote-back.vercel.app,.vercel.app
DJANGO_CORS_ALLOWED_ORIGINS=https://dmquote.netlify.app
DJANGO_CSRF_TRUSTED_ORIGINS=https://dmquote-back.vercel.app
DATABASE_ENGINE=postgresql
DATABASE_URL=<Neon-production-connection-string>
DATABASE_CONN_MAX_AGE=0
```

The public backend root is `https://dmquote-back.vercel.app/` and returns
`ok`. Its public API base is
`https://dmquote-back.vercel.app/api/v1`; Admin/login is at
`https://dmquote-back.vercel.app/dmlog/`.

Run migrations against Neon from a trusted local environment or a controlled
release job before testing the public deployment. Do not configure the import
or superuser-creation commands as a Vercel request handler.
