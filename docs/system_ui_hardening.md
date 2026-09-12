# System and UI Hardening

The September 2026 audit found unreachable confirmation dialogs, missing icons,
inconsistent dark themes, inaccessible mobile history navigation, unsafe answer
HTML, and avoidable authentication/history durability risks. Changes preserve
Vue, Pinia, Element Plus, SSE, QueryPipeline and the shared turn producer.

## Server boundaries

- Authentication remains owned by `api/auth/`. `APP_ENV=production` rejects a
  missing, short or known development signing key during lifespan startup and
  token use. Production cookies always require HTTPS. Development without a key
  uses a process-local random value, so a restart invalidates those sessions.
- `api/auth/limits.py` admits account and peer identities atomically before
  database/password work. Default limits are 10 attempts/account and 60/IP over
  60 seconds. The table is bounded and rejects new identities when full rather
  than evicting live restrictions. Password verification runs in FastAPI's
  worker pool. Limits are configurable in `.env.example`.
- `api/admission.py` is the sole HTTP chat-capacity owner. It supplies a typed
  `ChatLease` to the existing application/worker boundary, without making routing
  or teaching decisions. Defaults are 8 concurrent requests globally and 2 per
  student, including requests waiting for a session lock. Overload returns HTTP
  429 with `Retry-After` before history mutation or SSE response headers.
- A stream worker owns its lease until it finishes. SSE disconnect and replay do
  not release or acquire generation capacity. Cancellation while waiting and
  failed worker startup release capacity; startup failure removes the unaccepted
  question. Unexpected worker exceptions use a generic public message while the
  server logs retain diagnostic details.
- `api/state.py` remains the single history snapshot owner. It serializes before
  writing, flushes temporary files, publishes through atomic replacement and
  keeps the prior valid snapshot in `.json.bak` through a metadata-only hard
  link. A damaged primary is archived before restoring its valid backup. If no
  valid snapshot exists, corrupt files are quarantined as `.corrupt.*`, a
  critical log is emitted, and the service starts with an explicitly empty
  history so the API is operable without silently deleting evidence. Reload
  updates existing containers so consumers keep valid references.

Deployment remains one API process and one replica. The standard launch commands
explicitly use one worker. These changes do not introduce a shared task broker,
cross-process locks, a transactional history database or forced termination of
provider calls already in progress. Configure trusted proxy identities when
using IP limits. Production needs an HTTPS frontend endpoint and a random secret;
neither credentials nor running deployments are changed by this work.

## Answer rendering

`web/src/utils/markdown.js` uses DOMPurify with explicit Markdown tag and attribute
allowlists. Model-provided styles, application classes, forms, embedded media,
SVG/MathML and unsafe/relative URLs are removed. Code-block classes are kept for
highlighting and copy controls. Without a browser DOM, untrusted HTML is escaped
as text rather than passed to a separate regex sanitizer.

Math is extracted before Markdown parsing, and KaTeX with `trust: false` supplies
its own mathematical markup after untrusted HTML has been sanitized. Insertion
only replaces text nodes, never HTML attributes. This preserves formula layout
without trusting model-supplied positioning styles or KaTeX HTML extensions.

## Regression coverage

- `tests/integration/api/test_auth_hardening.py`: production startup, secure
  cookies, rejection of the published old development key, and admission before
  expensive password verification. The startup tests explicitly enter lifespan
  because the repository's same-thread TestClient does not run it automatically.
- `tests/test_auth_limits.py`: shared account/IP windows and bounded identity churn.
- `tests/integration/api/test_state_recovery.py`: failed atomic publication,
  corrupt/missing primaries, preserved archives, valid backup recovery, and
  refusal to replace damaged state.
- `tests/integration/api/test_chat_admission.py`: capacity across students and
  HTTP modes, worker ownership after disconnect, cancelled waiting requests,
  failed startup and safe exception projection.
- `web/tests/markdown-security.spec.js`: malicious layouts/forms/links,
  preservation of formulas/code/tables/citations, and math-in-attribute attacks.

API integration fixtures use temporary authentication, assessment and history
paths. Browser checks use mocked API responses; they do not submit real quizzes
or exercise external model/retrieval providers. Run the existing full Python
suite, Ruff gates, route harness and frontend build plus browser checks for final
integration acceptance.
