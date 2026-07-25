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

The DM Live importer is disabled by default and contains no live network operation
in this skeleton. Do not enable it until the source owner has granted permission.
