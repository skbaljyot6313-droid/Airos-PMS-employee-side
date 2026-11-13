# API versioning

`/api/v1` and `app/api/v1` define the first mobile contract boundary. Pydantic contracts exposed by these routes are imported through `app/schemas/v1/<domain>`.

A future incompatible contract belongs in `/api/v2`, `app/api/v2`, and `app/schemas/v2`. Models, repositories, and services remain shared unless domain behavior—not only representation—must diverge. Additive compatible changes stay in v1. Database models are not API-versioned.
