# Public Launch Rate Limits

The production Compose deployment applies a process-local sliding-window quota
of 600 authenticated business API requests per student per 3600 seconds. The
quota is an API-boundary abuse and polling guard; it does not replace the chat
model-generation admission queue or the external web-search provider quota.

The quota applies to the authenticated `sessions`, `chat`, `profile`,
`knowledge-map`, and `assessments` routers. Authentication endpoints,
liveness/readiness endpoints, and static frontend assets are outside this
quota. A rejected request returns HTTP `429` with a `Retry-After` header.

The assessment list polls pending preparation jobs every 15 seconds. Each
poll currently makes two authenticated API requests, so a student who leaves
that page open with a pending job consumes at most about 480 requests per
hour before ordinary interaction traffic. Keep this relationship in mind when
changing either the frontend polling interval or the production quota.

The limiter state lives in one API process. A deployment using multiple API
workers or instances must either keep the limit disabled or replace this
process-local owner with shared state such as Redis before treating the value
as deployment-wide. The current single-process Compose setup is the supported
launch shape.

Development and test configuration defaults the quota to `0` (disabled). Set
`API_PER_STUDENT_REQUESTS_PER_WINDOW` and
`API_REQUEST_QUOTA_WINDOW_SECONDS` explicitly when running another deployment
shape.
