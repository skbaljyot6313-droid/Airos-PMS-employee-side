# Mobile compatibility

Mobile base URL appends `/api/v1`. All paths below match exactly.

| Mobile screen/service | Call | New route | Request contract | Response contract | Result |
|---|---|---|---|---|---|
| Login | POST `/auth/login` | POST `/api/v1/auth/login` | `LoginRequest` | `AuthResponse` | PASS |
| Session restore | GET `/auth/me` | GET `/api/v1/auth/me` | Bearer token | `MeResponse` | PASS |
| Profile | PATCH `/auth/me` | PATCH `/api/v1/auth/me` | `UpdateProfileRequest` | user payload | PASS |
| Token refresh | POST `/auth/refresh` | POST `/api/v1/auth/refresh` | `RefreshRequest` | `TokenRefreshResponse` | PASS |
| Logout | POST `/auth/logout` | POST `/api/v1/auth/logout` | `LogoutRequest` | 204 | PASS |
| Task list | GET `/tasks?limit=200` | GET `/api/v1/tasks` | query limit | list with `items/total/page/limit` | PASS |
| Task detail | GET `/tasks/{uid}` | GET `/api/v1/tasks/{task_id}` | UUID path | task/history/submissions/evidence | PASS |
| Task detail | POST `/tasks/{uid}/start` | matching | UUID path | task | PASS |
| Task detail | POST `/tasks/{uid}/submit` | matching | `TaskSubmitRequest` | task | PASS |
| Task filters | GET `/zones` | GET `/api/v1/zones` | Bearer token | zone list | PASS |
| Maintenance tab | GET `/maintenance` | GET `/api/v1/maintenance` | Bearer token | ticket list | PASS |
| Maintenance detail | GET `/maintenance/{uid}` | matching | UUID path | ticket/events/attachments | PASS |
| New maintenance | GET `/maintenance/eligible-locations` | matching | Bearer token | rooms + dorms | PASS |
| New maintenance | POST `/maintenance` | matching | `MaintenanceCreateRequest` | ticket | PASS |
| Maintenance detail | POST `/{uid}/start` | matching | UUID path | ticket | PASS |
| Maintenance detail | POST `/{uid}/resolve` | matching | `MaintenanceResolveRequest` | ticket | PASS |
| Evidence picker | POST `/media/uploads` | POST `/api/v1/media/uploads` | multipart `file` | `{url,key}` | PASS |

OpenAPI route registration is enforced by `tests/api/test_openapi_contract.py`. Wire serializers remain the existing v1 serializers, preserving `*_uid`, status strings, nullability, nested history, and FastAPI error envelopes.
