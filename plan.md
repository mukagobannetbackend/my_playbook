# TradeVault implementation plan

## Product and implementation

TradeVault is a responsive, mobile-first trading screenshot journal for fast capture and private reflection on phones and computers. Implement it as a Python 3 Flask app with server-rendered Jinja templates, semantic HTML, CSS and small progressive-enhancement JavaScript. Use Flask-Login, Flask-WTF/CSRF, SQLAlchemy, a managed MySQL database in deployment (SQLite only as a local fallback), and secure password hashing. Email/password sign-up, sign-in, logout, password changes and email password recovery are application-managed; user credentials never go to the browser. Recovery uses a single-use, hashed, expiring token sent over configurable SMTP, with generic anti-enumeration copy. Recovery-email sending requires SMTP credentials and a public `APP_BASE_URL`.

Store screenshot bytes in durable object storage, never the production container filesystem. Use random owner-scoped object keys and persist each image's storage key and metadata in SQL. Keep a local-only upload adapter for non-production development and explicit setup documentation; production storage uses the managed storage presign API when its runtime credentials are available and fails closed otherwise. Validate file size/type, authorize every read/write by owner, and retain soft-deleted records rather than implying physical object deletion.

The journal supports screenshot creation, viewing, metadata editing, soft-delete, autosaved reflection notes, single-image and selected ZIP downloads, search/date filters, chronological day groupings, and same-day near-duplicate groupings. Use an average image hash plus a configurable Hamming-distance threshold for similarity; comparisons are discovery aids, not trading signals. Provide onboarding, responsive navigation, an in-app notification center/preferences, and account/settings screens.

## Project structure

- `app.py` / `tradevault/__init__.py`: application factory, safe configuration, database TLS adapter, extensions, health route and route registration.
- `tradevault/models.py`: accounts, journal entries, password reset tokens and in-app notification models.
- `tradevault/auth.py`: sign-up/sign-in/logout, email password recovery, password changes and account session invalidation.
- `tradevault/journal.py`: screenshot upload/view/edit/soft-delete, search/filter, day and similarity review, downloads, notes and notification preferences.
- `tradevault/storage.py`: durable-object adapter, development-only local adapter and signed retrieval/upload support.
- `tradevault/templates/`: accessible responsive pages and shared layout.
- `tradevault/static/css/` and `tradevault/static/js/`: visual system and small progressive enhancements.
- `migrations/`: deterministic initial database schema and Alembic migration support.
- `tests/`: isolated Flask route, model and security behavior checks.
- `Dockerfile`, `requirements.txt`, `.env.example`, `README.md`, `TODO.md`: production container, pinned dependencies, configuration guide, deployment instructions and outcomes.
- `public/manus-routes.json`: declared page routes for WebDev.

## Design direction

Style candidates: soft observatory ledger (0.061), crisp market editorial (0.037), quiet neo-brutalist toolkit (0.084). Selected: **soft observatory ledger**—a modern, calm, light-first workspace with deep ink text, warm chalk surfaces, and a distinctive vivid-jade accent. Avoid trading-terminal intimidation and decorative chart clutter.

- **Design Movement:** Contemporary editorial software design with restrained financial-instrument cues.
- **Core Principles:** Capture in seconds; calm reflection over performance judgment; clear hierarchy at mobile widths; data-rich without visual noise.
- **Color Philosophy:** Warm off-white reduces glare and feels like a private notebook; ink establishes confidence; jade marks actions and positive activity without implying trade success; subdued amber marks prompts and pending states.
- **Layout Paradigm:** Offset sidebar-and-canvas on desktop; compact bottom navigation and a single-column chronological stream on mobile; filters sit beside the title rather than above a grid.
- **Signature Elements:** Small jade orbit/ring mark; screenshot cards with softly layered paper edges; a date rail that guides the journal timeline.
- **Interaction Philosophy:** One obvious primary capture action; autosave with quiet saved status; prompts are optional and non-judgmental; destructive operations require a clear confirm step.
- **Animation:** Short 140–220 ms transitions for navigation, save confirmation and card expansion; respect `prefers-reduced-motion`; no pulsing or flashing market cues.
- **Typography System:** DM Sans for interface and DM Mono for timestamps and compact trading metadata; compact sentence-case page headings; body text no smaller than 14px.
- **Brand Essence:** A private place to preserve the thinking behind each trading chart; thoughtful, composed, dependable.
- **Brand Voice:** Gentle, specific, never prescriptive. Examples: “What did you notice before the entry?” and “A note can be unfinished. It’s still yours.”
- **Wordmark & Logo:** A custom CSS orbit/rising-sun glyph paired with the TradeVault wordmark, not an unstyled text logo.
- **Signature Brand Color:** Jade `#2EBE91`.

## Serving and deployment

Run Flask on the runtime `PORT`, default 3000, bound to `0.0.0.0`. Include a root Dockerfile using Python 3.12, pinned application dependencies and Gunicorn. Provide an unauthenticated health endpoint and explicit, repeatable migrations. Production session cookies are `HttpOnly; Secure; SameSite=None` for the HTTPS Preview frame; local HTTP development can opt out of `Secure`. Adapt the managed MySQL URL's SSL policy to a verified CA bundle for PyMySQL. Unit tests use isolated SQLite and local test storage. The initial migration was applied only after confirming the project's managed database contained no tables; deployment uses the same tracked migration. Configure the WebDev container declaration and health path; do not publish without an explicit publish request. SMTP settings are required to deliver password recovery. The project ZIP contains source/config/docs only, not credentials, user data, local uploads or VCS internals.
