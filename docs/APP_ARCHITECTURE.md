# JetPay24 — Django App Architecture

**Document type:** Technical Architecture — App Structure Design  
**Status:** Approved for implementation  
**Related documents:** `docs/PRODUCT_SPEC.md`, `docs/PHASE1_AUTH_PLAN.md`

---

## 1. Guiding Principles

Every architectural decision in this document is made against six requirements that
a production-grade financial services platform cannot compromise on.

**Bounded domains.** Each app owns exactly one business domain. It owns the models
for that domain, the business logic that mutates those models, and the signals or
service functions that other apps may call. No app reaches into another app's models
to write data directly — it calls a service function.

**Dependency direction is one-way.** The dependency graph is a DAG (directed acyclic
graph). Lower-level apps (`accounts`, `core`) know nothing about higher-level apps
(`orders`, `kyc`). Higher-level apps import from lower-level ones, never the reverse.

**API-first from day one.** Every feature that a customer or admin touches must be
reachable via a DRF endpoint. Template-rendered views are a thin convenience layer
on top, not the canonical surface. This is what makes the same backend serve
`jetpay24.com`, `panel.jetpay24.com`, and future mobile apps without duplication.

**No fat models, no fat views.** Business logic lives in service modules
(`app/services.py`) or domain-specific managers. Models hold data and simple
derived properties. Views hold only request/response translation.

**Financial operations are transactional and audited.** Any function that moves
money — wallet credits, debits, order settlement, manual adjustments — is wrapped
in a database transaction, generates an audit log entry, and is idempotent by design.

**The `core` app is the foundation, not a dumping ground.** Shared utilities, the
audit log, abstract base models, and cross-cutting helpers live in `core`. It must
never import from any domain app.

---

## 2. Complete App Inventory

The full target structure contains 13 Django apps plus the project config package.

```text
config/             ← Django project package (settings, root URLs, WSGI, ASGI)
apps/
├── core/           ← Shared foundations: audit log, abstract models, utilities
├── accounts/       ← Users, authentication, sessions, OTP tokens
├── profiles/       ← Customer profile, KYC-adjacent personal data
├── kyc/            ← Identity verification, documents, bank cards, review workflow
├── orders/         ← Service categories, orders, status workflow, documents
├── wallet/         ← Ledger, transactions, deposits, withdrawals
├── payments/       ← Payment intents, provider integration, receipts
├── support/        ← Tickets, live chat, AI assistant escalation
├── content/        ← Blog, articles, FAQ, static pages, SEO
├── rates/          ← Exchange rates, USDT, crypto prices, converter
├── notifications/  ← Multi-channel delivery, preferences, templates
├── pages/          ← Public marketing views (exists today, will evolve)
└── api/            ← DRF routing, versioning, shared serializers, permissions
```

The `apps/` subdirectory is a packaging convention that keeps domain apps separated
from the `config/` package. Each app registers itself as `apps.accounts`,
`apps.orders`, etc. in `INSTALLED_APPS`.

---

## 3. App Specifications

---

### 3.1 `core`

**Role:** Foundation layer. Every other app may depend on `core`. `core` depends on nothing inside the project.

**Responsibilities:**
- Abstract base model providing `created_at`, `updated_at`, `uuid` on all domain models.
- `AuditLog` model and the `audit()` service function that all apps call.
- Shared custom exceptions (`JetPayError`, `InsufficientFundsError`, `PermissionDeniedError`, etc.).
- Shared validators (phone format, IBAN format, file type/size).
- Shared constants (status codes, error codes, choices shared across apps).
- Utility functions: Persian number formatting, Jalali date helpers, slug generation.
- Custom Django management commands: `reconcile_wallets`, `expire_tokens`, `sync_rates`.
- Health check endpoint (`/health/`).

**Models owned:**

| Model | Purpose |
|---|---|
| `AuditLog` | Append-only record of every sensitive action across the platform |
| `SiteConfiguration` | Key-value store for runtime configuration managed via admin |

**`AuditLog` fields:**  
`actor` (FK User, nullable for system), `action` (str, e.g. `order.status_changed`),
`target_type`, `target_id`, `metadata` (JSONField), `ip_address`, `user_agent`, `created_at`.

**Depends on:** Django internals only.  
**Depended on by:** every app.

---

### 3.2 `accounts`

**Role:** Identity — who a user is and how they prove it.

**Responsibilities:**
- Custom `User` model (replaces `auth.User`, login via email).
- User registration, email verification, login, logout, password reset.
- OTP code generation and verification (Phase 1 stub, Phase 2 active).
- Session management and device tracking.
- Staff role and permission assignment.
- `AUTH_USER_MODEL = 'accounts.User'` — this setting must be set before the first migration.

**Models owned:**

| Model | Purpose |
|---|---|
| `User` | Platform identity. Fields: `email`, `phone`, `first_name`, `last_name`, `is_active`, `is_email_verified`, `is_phone_verified`, `is_staff`, `date_joined` |
| `UserManager` | Custom manager; creates users with email as identifier |
| `EmailVerificationToken` | One-time 24-hour link for email activation |
| `PasswordResetToken` | One-time 1-hour link for password reset |
| `OTPCode` | Hashed mobile OTP; purpose-scoped (LOGIN, REGISTER, PHONE_VERIFY, PASSWORD_RESET) |
| `UserSession` | Device and session tracking for the "active sessions" security feature |

**Service functions (in `accounts/services.py`):**
- `create_user(email, password, first_name, last_name, phone=None)`
- `verify_email(token_string)`
- `request_password_reset(email)`
- `confirm_password_reset(token_string, new_password)`
- `send_otp(phone, purpose)`
- `verify_otp(phone, code, purpose)`

**Depends on:** `core`  
**Depended on by:** every app that needs `request.user` or a FK to `User`.

**Critical note:** Because `AUTH_USER_MODEL` points here, `accounts` must be listed
first among project apps in `INSTALLED_APPS` and its migration must run before all others.

---

### 3.3 `profiles`

**Role:** What we know about a user beyond their identity credentials.

Deliberately separated from `accounts` because profile data has a different lifecycle
(it grows over time), different access patterns (public-facing name vs. private credentials),
and in the future may be extracted to a separate service. Keeping it separate also
avoids turning `accounts` into a bloated "user bucket" app.

**Responsibilities:**
- Extended personal information (birth date, national ID, address).
- Preferred language and UI settings.
- Avatar management.
- The `Profile` is created automatically via a `post_save` signal when a `User` is created.

**Models owned:**

| Model | Purpose |
|---|---|
| `Profile` | 1:1 with `User`. Fields: `birth_date`, `national_id` (encrypted), `address`, `city`, `province`, `postal_code`, `preferred_language`, `avatar` |
| `UserSettings` | Notification preferences, 2FA preference, language — separate from profile for clarity |

**Service functions:**
- `get_or_create_profile(user)`
- `update_profile(user, data)`

**Depends on:** `core`, `accounts`  
**Depended on by:** `kyc`, `notifications`, `api`

---

### 3.4 `kyc`

**Role:** Identity verification — confirming who the user says they are.

**Responsibilities:**
- Collecting and storing identity documents (national ID scan, selfie, video, declaration, bank card scan).
- Managing the KYC review workflow: NOT_STARTED → PENDING → APPROVED / REJECTED / RESUBMIT.
- Bank card verification (masking, IBAN storage, verified flag).
- Enforcement of KYC tier limits on orders and withdrawals.
- Admin-facing review queue and approval/rejection actions.

Documents are stored in **private** object storage. URLs are generated as short-lived
signed URLs for reviewers — never served as static public files.

**Models owned:**

| Model | Purpose |
|---|---|
| `KYCProfile` | 1:1 with `User`. Tracks overall KYC status, tier, review timestamps, rejection reason |
| `KYCDocument` | Each uploaded document. Fields: `type` (NATIONAL_ID, SELFIE, VIDEO, DECLARATION), `file_ref` (private storage key), `status`, `uploaded_at`, `reviewer_notes` |
| `BankCard` | Verified bank cards. Fields: `card_number_masked`, `iban`, `holder_name`, `status`, `verified_at` |
| `KYCReviewEvent` | Audit trail of every reviewer action on a KYC submission |

**Service functions:**
- `submit_kyc(user)`
- `approve_kyc(kyc_profile, reviewer, notes)`
- `reject_kyc(kyc_profile, reviewer, reason)`
- `request_resubmission(kyc_profile, reviewer, reason)`
- `add_bank_card(user, card_number, iban, holder_name)`
- `get_kyc_tier(user)` → used by `orders` and `wallet` to enforce limits

**Depends on:** `core`, `accounts`, `profiles`, `notifications`  
**Depended on by:** `orders` (tier checks), `wallet` (withdrawal eligibility)

---

### 3.5 `orders`

**Role:** The core transactional domain — service requests from customers.

This app exists today (partially). Its current implementation has guest-only orders
with plain `name`/`phone`/`email` fields. It will be extended to support authenticated
users, a richer status workflow, status history, and document management.

**Responsibilities:**
- Managing the service catalogue (`ServiceCategory`).
- Order creation, status workflow, and document attachment.
- Generating and managing public tracking codes.
- Enforcing KYC tier limits per order value/type.
- Status history — immutable log of every transition.
- Linking orders to wallet settlement (calling `wallet` services, never importing wallet models directly).

**Models owned:**

| Model | Purpose |
|---|---|
| `ServiceCategory` | Master list of payment services. Fields: `slug`, `name_fa`, `name_en`, `description`, `icon`, `min_amount`, `max_amount`, `kyc_tier_required`, `is_active`, `sort_order` |
| `Order` | Core order record. Fields: `tracking_code`, `user` (FK, nullable for legacy guests), `service` (FK), `amount`, `currency`, `description`, `status`, `assigned_to` (staff FK), `created_at`, `updated_at` |
| `OrderDocument` | Files attached to an order. Fields: `order`, `file_ref`, `type`, `uploaded_at` |
| `OrderStatusHistory` | Immutable append-only log. Fields: `order`, `from_status`, `to_status`, `changed_by`, `note`, `created_at` |

**Status choices:** SUBMITTED, UNDER_REVIEW, WAITING_FOR_PAYMENT, PROCESSING, COMPLETED, REJECTED.

**Service functions:**
- `create_order(user, service_slug, amount, description, documents)`
- `transition_order_status(order, new_status, actor, note)`
- `get_order_by_tracking_code(code)` → public tracking, returns limited fields only

**Depends on:** `core`, `accounts`, `kyc` (for tier checks), `notifications`, `wallet` (called via service function, not model import)  
**Depended on by:** `wallet` (settlement references), `api`

**Migration path:** The current `orders` app migration chain (0001–0003) will gain new
migrations adding `user` FK, `assigned_to` FK, updated status choices, and
`ServiceCategory`. Existing guest orders are preserved with `user=NULL`.

---

### 3.6 `wallet`

**Role:** Financial ledger — the source of truth for customer funds.

This is the most sensitive app in the system. It must be implemented with strict
transaction discipline: every mutation is wrapped in `select_for_update` and an atomic
database transaction, every entry is append-only, and balances are always derived
or verified from the ledger rather than trusted blindly.

**Responsibilities:**
- One wallet per user (created automatically when a user registers).
- Append-only double-entry ledger via `WalletTransaction`.
- Deposit recording (confirms from `payments` app).
- Withdrawal requests and their admin approval workflow.
- Order settlement debits and refund credits.
- Admin manual adjustments (with mandatory reason and audit log).
- Balance reconciliation.

**Models owned:**

| Model | Purpose |
|---|---|
| `Wallet` | One per user. Fields: `user` (1:1), `currency` (default IRR), `balance_cached` (derived, reconciled), `status` (ACTIVE, FROZEN, CLOSED) |
| `WalletTransaction` | Append-only ledger entry. Fields: `wallet`, `type` (DEPOSIT, WITHDRAWAL, ORDER_DEBIT, ORDER_REFUND, ADJUSTMENT, FEE), `direction` (CREDIT/DEBIT), `amount`, `balance_after`, `reference_type`, `reference_id`, `idempotency_key`, `created_by`, `note`, `created_at` |
| `WithdrawalRequest` | Fields: `wallet`, `amount`, `destination_card` (FK to `kyc.BankCard`), `status`, `reviewed_by`, `reviewed_at`, `rejection_reason` |

**Service functions:**
- `credit(wallet, amount, type, reference, idempotency_key, note, actor)`
- `debit(wallet, amount, type, reference, idempotency_key, note, actor)`
- `request_withdrawal(user, amount, card_id)`
- `approve_withdrawal(withdrawal_request, reviewer)`
- `reject_withdrawal(withdrawal_request, reviewer, reason)`
- `admin_adjust(wallet, amount, direction, reason, admin_user)`
- `get_balance(wallet)` — recalculates from ledger; does not trust `balance_cached` alone

**Critical rules:**
- `credit` and `debit` must use `select_for_update` on the wallet row.
- `balance_after` is written atomically with the transaction.
- `idempotency_key` is unique per wallet — retried operations return the existing record.
- No function in this app may call `orders` or `kyc` models directly.
  It receives IDs as reference strings and emits signals.

**Depends on:** `core`, `accounts`, `kyc` (for withdrawal eligibility check only), `notifications`  
**Depended on by:** `orders` (settlement), `payments` (deposit confirmation), `api`

---

### 3.7 `payments`

**Role:** The bridge between the external payment world and the internal wallet ledger.

`payments` is deliberately separated from `wallet`. `wallet` is a pure ledger — it
records what happened to funds internally. `payments` is the integration layer —
it tracks what the payment gateway said, reconciles gateway events with internal
records, and calls `wallet.credit` when a deposit is confirmed.

**Responsibilities:**
- Creating payment intents when a customer initiates a deposit.
- Receiving and verifying webhooks or manual confirmations from payment providers.
- Recording receipt/proof of payment against an order or wallet deposit.
- Handling refund triggers (calling `wallet.credit` with `ORDER_REFUND` type).
- Idempotent processing of provider callbacks.

**Models owned:**

| Model | Purpose |
|---|---|
| `PaymentIntent` | Represents an initiated payment. Fields: `user`, `order` (FK, nullable), `amount`, `currency`, `provider`, `status` (PENDING, CONFIRMED, FAILED, REFUNDED), `idempotency_key`, `created_at` |
| `PaymentEvent` | Raw event log from provider callbacks. Fields: `intent`, `event_type`, `payload` (JSONField), `received_at`, `processed_at` |
| `Receipt` | Confirmed payment proof. Fields: `intent`, `external_reference`, `confirmed_at`, `amount`, `notes` |

**Service functions:**
- `create_payment_intent(user, amount, order=None)`
- `confirm_payment(intent_id, external_ref, actor)` → calls `wallet.credit`
- `process_webhook(provider, payload)` → idempotent
- `initiate_refund(order, reason)` → calls `wallet.credit` with REFUND type

**Depends on:** `core`, `accounts`, `orders`, `wallet`  
**Depended on by:** `api`

---

### 3.8 `support`

**Role:** Customer communication — help tickets, live chat, AI assistant.

**Responsibilities:**
- Ticket creation, threading, and lifecycle management.
- Internal agent notes (hidden from customers).
- Live chat sessions between customers and agents.
- AI assistant integration: receive message, call AI provider API, store response.
- Escalation: convert an AI session to a live ticket or chat, carrying context.

**Models owned:**

| Model | Purpose |
|---|---|
| `Ticket` | Fields: `user`, `subject`, `category`, `priority`, `status` (OPEN, PENDING, ANSWERED, CLOSED), `assigned_to` (staff), `created_at`, `updated_at` |
| `TicketMessage` | Fields: `ticket`, `sender_type` (CUSTOMER, AGENT, AI), `sender` (FK User, nullable for AI), `body`, `is_internal`, `attachments`, `created_at` |
| `ChatSession` | Fields: `user`, `agent` (FK, nullable), `status` (WAITING, ACTIVE, CLOSED), `started_at`, `ended_at` |
| `ChatMessage` | Fields: `session`, `sender_type`, `sender`, `body`, `created_at` |
| `AIConversation` | Tracks AI assistant threads per user/session for escalation context. Fields: `user` (nullable), `session_key`, `messages` (JSONField), `escalated`, `created_at` |

**Service functions:**
- `create_ticket(user, subject, category, body)`
- `reply_to_ticket(ticket, sender, body, is_internal)`
- `close_ticket(ticket, agent)`
- `open_chat_session(user)`
- `assign_chat_agent(session, agent)`
- `ai_respond(conversation_id, user_message)` → calls AI provider
- `escalate_ai_to_ticket(conversation_id, user)`

**Depends on:** `core`, `accounts`, `notifications`  
**Depended on by:** `api`

---

### 3.9 `content`

**Role:** Everything published on the public website that is editorial rather than transactional.

**Responsibilities:**
- Blog posts and educational articles with bilingual support.
- Taxonomy (categories, tags).
- FAQ items.
- CMS-style static pages (About, Terms, Privacy).
- SEO metadata per content item.
- Draft/publish workflow.

**Models owned:**

| Model | Purpose |
|---|---|
| `Post` | Blog post or educational article. Fields: `slug`, `type` (BLOG, ARTICLE), `title`, `excerpt`, `body`, `cover_image`, `locale`, `status` (DRAFT, PUBLISHED, ARCHIVED), `author` (FK User), `published_at`, `seo_title`, `seo_description`, `seo_keywords` |
| `Category` | Hierarchical taxonomy. Fields: `name`, `slug`, `parent` (self-FK), `locale` |
| `Tag` | Flat taxonomy. Fields: `name`, `slug` |
| `PostCategory` | M:N through model with sort order |
| `PostTag` | M:N through model |
| `FAQCategory` | Fields: `name`, `slug`, `locale`, `sort_order` |
| `FAQItem` | Fields: `category`, `question`, `answer`, `locale`, `sort_order`, `is_active` |
| `StaticPage` | Fields: `slug`, `title`, `body`, `locale`, `is_published`, `seo_*` |

**Service functions:**
- `get_published_posts(locale, category=None, tag=None, page=1)`
- `get_post_by_slug(slug, locale)`
- `get_faq_items(locale, category=None)`
- `get_static_page(slug, locale)`

**Depends on:** `core`, `accounts` (for author FK)  
**Depended on by:** `pages`, `api`

---

### 3.10 `rates`

**Role:** Live and historical exchange rate data displayed on the public site.

This app is **read-oriented**. It fetches rates from external providers (via Celery
periodic tasks), stores them, allows manual admin overrides, and serves them to
the front end. It does not perform currency conversion with financial consequences
— the converter feature is purely informational display.

**Responsibilities:**
- Defining rate sources (FX providers, USDT exchange, crypto price feeds).
- Periodic background fetching of rates via Celery beat tasks.
- Manual admin override of any rate.
- Serving current rates and historical snapshots.
- Currency converter calculation endpoint (client-side or API).

**Models owned:**

| Model | Purpose |
|---|---|
| `RateSource` | Fields: `name`, `type` (FX, USDT, CRYPTO), `endpoint_url`, `fetch_interval_seconds`, `is_active` |
| `Rate` | Current rate snapshot. Fields: `source`, `symbol` (e.g. USD/IRR), `buy`, `sell`, `mid`, `fetched_at`, `is_manual_override`, `overridden_by` |
| `RateHistory` | Append-only historical record. Fields: `symbol`, `mid`, `source`, `recorded_at` |

**Service functions:**
- `get_current_rates(type)` → returns latest rates by type
- `get_rate(symbol)` → single pair
- `set_manual_override(symbol, buy, sell, admin_user)` → with audit log
- `convert(amount, from_symbol, to_symbol)` → informational only

**Celery tasks:**
- `fetch_fx_rates` — periodic
- `fetch_usdt_rates` — periodic
- `fetch_crypto_prices` — periodic

**Depends on:** `core`  
**Depended on by:** `pages`, `api`

---

### 3.11 `notifications`

**Role:** Delivering messages to users across all channels.

No other app sends notifications directly via email/SMS/push. They call
`notifications.services.notify(user, event_type, context)`. This ensures:
- Channel routing is centralized.
- User preferences are respected.
- All notification delivery is async.
- Templates are managed in one place.

**Responsibilities:**
- Storing in-app notifications and marking them read.
- Rendering locale-aware notification templates (FA/EN).
- Routing to the correct channel(s) based on event type and user preferences.
- Email delivery (via Django email backend + Celery task).
- SMS delivery (via SMS gateway + Celery task).
- Push delivery (via FCM/APNs when mobile apps exist).
- Retry logic with exponential backoff for failed deliveries.

**Models owned:**

| Model | Purpose |
|---|---|
| `Notification` | In-app record. Fields: `user`, `event_type`, `title`, `body`, `channel`, `is_read`, `read_at`, `metadata` (JSONField), `created_at` |
| `NotificationPreference` | Per-user, per-event-type, per-channel preference. Fields: `user`, `event_type`, `channel`, `enabled` |
| `NotificationTemplate` | Admin-editable message templates. Fields: `event_type`, `channel`, `locale`, `subject_template`, `body_template` |
| `DeliveryLog` | Tracks send attempts and outcomes. Fields: `notification`, `channel`, `status`, `attempt_count`, `last_attempted_at`, `error_detail` |

**Service functions:**
- `notify(user, event_type, context, channels=None)` — the universal entry point
- `mark_read(notification_id, user)`
- `get_unread_count(user)`
- `get_inbox(user, page)`

**Celery tasks:**
- `send_email_notification(notification_id)`
- `send_sms_notification(notification_id)`
- `send_push_notification(notification_id, device_tokens)`

**Event types (examples):** `auth.email_verified`, `kyc.approved`, `kyc.rejected`,
`order.status_changed`, `wallet.credited`, `wallet.debited`, `ticket.replied`,
`chat.agent_joined`.

**Depends on:** `core`, `accounts`  
**Depended on by:** `accounts` (auth emails are a special case — see §4 below), `kyc`, `orders`, `wallet`, `support`

**Special case — auth emails:** `EmailVerificationToken` and `PasswordResetToken` emails
are sent from within `accounts/emails.py` directly, not via `notifications`. This is because
they must fire before the user is fully active and before preferences are established.
All post-activation notifications go through `notifications`.

---

### 3.12 `pages`

**Role:** Public-facing template views for the marketing website.

This app exists today. It will remain thin — primarily view functions and URL routing
that pull data from `content`, `rates`, and `orders` (for the public tracking page,
which currently lives in `orders/views.py` and should migrate here).

**Responsibilities:**
- Rendering the home page.
- Rendering service landing pages (data from `orders.ServiceCategory`).
- Rendering the blog/article list and detail (data from `content`).
- Rendering the FAQ page (data from `content`).
- Rendering rate pages and currency converter (data from `rates`).
- Rendering the contact page with a form.
- Hosting the public order tracking page.
- Sitemap generation.
- `robots.txt`.

**Models owned:** None. This app is view-only; it renders data owned by other apps.

**Depends on:** `core`, `content`, `rates`, `orders` (tracking view)  
**Depended on by:** nothing

---

### 3.13 `api`

**Role:** DRF routing, versioning, shared serializer infrastructure, and cross-cutting API concerns.

This is not a business domain app — it owns no models. Its purpose is to
keep DRF infrastructure (router, version negotiation, permission classes,
exception handler, pagination) in one place rather than scattered across
every business app.

**Responsibilities:**
- Root DRF router mounting all app-level routers under `/api/v1/`.
- Shared `BaseSerializer` with locale-aware field rendering.
- Shared permission classes: `IsVerifiedCustomer`, `IsStaffWithRole`, `IsKYCApproved`.
- Shared pagination class.
- Custom exception handler mapping domain exceptions to HTTP responses.
- Throttling configuration.
- JWT authentication class (using `djangorestframework-simplejwt`).
- OpenAPI schema generation configuration.

**Structure:**

```text
api/
├── __init__.py
├── apps.py
├── urls.py             ← root API router
├── permissions.py      ← shared DRF permission classes
├── pagination.py       ← shared pagination
├── exceptions.py       ← maps domain exceptions → HTTP errors
├── serializers.py      ← shared base serializers
├── throttling.py       ← rate limit classes
└── v1/
    ├── __init__.py
    ├── urls.py
    ├── auth/           ← accounts endpoints
    ├── profile/        ← profiles endpoints
    ├── kyc/            ← kyc endpoints
    ├── orders/         ← orders endpoints
    ├── wallet/         ← wallet endpoints
    ├── support/        ← support endpoints
    ├── content/        ← content endpoints (public)
    └── rates/          ← rates endpoints (public)
```

Each sub-package under `v1/` contains `views.py`, `serializers.py`, and `urls.py`
specific to that domain. This is where DRF ViewSets live — the domain app itself
contains only the business logic, not the HTTP serialization.

**Depends on:** `core`, all business apps  
**Depended on by:** nothing inside Django; consumed by external clients

---

## 4. Dependency Graph

The following shows the allowed import direction. An arrow means "may import from".
No reverse imports are permitted.

```text
                          ┌──────────────┐
                          │     core     │
                          └──────┬───────┘
                                 │ (everyone imports core)
         ┌───────────────────────┼─────────────────────────────────┐
         │                       │                                 │
    ┌────▼─────┐          ┌──────▼──────┐                  ┌──────▼──────┐
    │ accounts │          │    rates    │                   │   content   │
    └────┬─────┘          └──────┬──────┘                  └──────┬──────┘
         │                       │                                 │
    ┌────▼─────┐                 │ (read-only by pages)            │
    │ profiles │                 │                                 │
    └────┬─────┘                 └──────────────┐                  │
         │                                      │                  │
    ┌────▼─────┐                         ┌──────▼──────────────────▼──┐
    │   kyc    │                         │          pages             │
    └────┬─────┘                         └────────────────────────────┘
         │                               (no models; thin view layer)
    ┌────▼──────────────┐
    │   notifications   │ ◄── called by: kyc, orders, wallet, support, accounts
    └────┬──────────────┘
         │
    ┌────▼─────┐
    │  orders  │
    └────┬─────┘
         │
    ┌────▼─────┐
    │  wallet  │◄──────────────────────────────┐
    └────┬─────┘                               │
         │                                     │
    ┌────▼──────┐                      ┌───────┴──────┐
    │  payments │                      │   support    │
    └────┬──────┘                      └──────────────┘
         │
    ┌────▼─────┐
    │   api    │ ◄── consumes all business apps; exposes HTTP layer
    └──────────┘
```

**Rules enforced by this graph:**
- `core` imports nothing from the project.
- `accounts` imports only `core`.
- `profiles` imports `core` and `accounts`.
- `kyc` imports `core`, `accounts`, `profiles`. It calls `notifications` but does not import notification models — it calls `notifications.services.notify()`.
- `orders` imports `core`, `accounts`, `kyc`. It does not import `wallet.models`. It calls `wallet.services.debit()` by passing an order reference.
- `wallet` imports `core`, `accounts`, `kyc` (for withdrawal eligibility). It does not import `orders.models`.
- `payments` imports `core`, `accounts`, `orders`, `wallet`.
- `notifications` imports `core`, `accounts`. It does not import any domain app.
- `support` imports `core`, `accounts`, `notifications`.
- `content` imports `core`, `accounts` (author FK only).
- `rates` imports `core` only.
- `pages` imports `core`, `content`, `rates`, `orders`. It is the only app allowed to import from multiple domain apps simultaneously because it is a view-composition layer with no business logic.
- `api` imports everything — it is the outermost layer.

---

## 5. Model Ownership Summary

| Model | Owned by | FK references |
|---|---|---|
| `AuditLog` | `core` | `accounts.User` (nullable) |
| `SiteConfiguration` | `core` | — |
| `User` | `accounts` | — |
| `EmailVerificationToken` | `accounts` | `accounts.User` |
| `PasswordResetToken` | `accounts` | `accounts.User` |
| `OTPCode` | `accounts` | `accounts.User` (nullable) |
| `UserSession` | `accounts` | `accounts.User` |
| `Profile` | `profiles` | `accounts.User` (1:1) |
| `UserSettings` | `profiles` | `accounts.User` (1:1) |
| `KYCProfile` | `kyc` | `accounts.User` (1:1) |
| `KYCDocument` | `kyc` | `kyc.KYCProfile` |
| `BankCard` | `kyc` | `accounts.User` |
| `KYCReviewEvent` | `kyc` | `kyc.KYCProfile`, `accounts.User` |
| `ServiceCategory` | `orders` | — |
| `Order` | `orders` | `accounts.User` (nullable), `orders.ServiceCategory`, `accounts.User` (assigned_to) |
| `OrderDocument` | `orders` | `orders.Order` |
| `OrderStatusHistory` | `orders` | `orders.Order`, `accounts.User` |
| `Wallet` | `wallet` | `accounts.User` (1:1) |
| `WalletTransaction` | `wallet` | `wallet.Wallet`, `accounts.User` (created_by) |
| `WithdrawalRequest` | `wallet` | `wallet.Wallet`, `kyc.BankCard`, `accounts.User` (reviewer) |
| `PaymentIntent` | `payments` | `accounts.User`, `orders.Order` (nullable) |
| `PaymentEvent` | `payments` | `payments.PaymentIntent` |
| `Receipt` | `payments` | `payments.PaymentIntent` |
| `Ticket` | `support` | `accounts.User`, `accounts.User` (assigned_to) |
| `TicketMessage` | `support` | `support.Ticket`, `accounts.User` (nullable) |
| `ChatSession` | `support` | `accounts.User`, `accounts.User` (agent) |
| `ChatMessage` | `support` | `support.ChatSession`, `accounts.User` (nullable) |
| `AIConversation` | `support` | `accounts.User` (nullable) |
| `Post` | `content` | `accounts.User` (author) |
| `Category` | `content` | `content.Category` (self) |
| `Tag` | `content` | — |
| `FAQCategory` | `content` | — |
| `FAQItem` | `content` | `content.FAQCategory` |
| `StaticPage` | `content` | — |
| `RateSource` | `rates` | — |
| `Rate` | `rates` | `rates.RateSource`, `accounts.User` (override) |
| `RateHistory` | `rates` | `rates.RateSource` |
| `Notification` | `notifications` | `accounts.User` |
| `NotificationPreference` | `notifications` | `accounts.User` |
| `NotificationTemplate` | `notifications` | — |
| `DeliveryLog` | `notifications` | `notifications.Notification` |

---

## 6. `INSTALLED_APPS` Declaration

The order matters. Apps must appear after their dependencies.

```python
INSTALLED_APPS = [
    # Django built-ins
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'storages',               # django-storages for S3-compatible object storage
    'django_celery_beat',     # periodic task scheduling
    'django_celery_results',  # task result storage

    # Foundation (no internal dependencies)
    'apps.core',
    'apps.accounts',          # AUTH_USER_MODEL must resolve here

    # Identity layer
    'apps.profiles',

    # Domain apps (ordered by dependency depth)
    'apps.kyc',
    'apps.orders',
    'apps.wallet',
    'apps.payments',
    'apps.support',
    'apps.content',
    'apps.rates',
    'apps.notifications',

    # Presentation / API
    'apps.pages',
    'apps.api',
]
```

---

## 7. URL Structure

```python
# config/urls.py

urlpatterns = [
    # Django admin (operations-facing)
    path('admin/', admin.site.urls),

    # Auth (session-based, for Django templates + future DRF auth)
    path('auth/', include('apps.accounts.urls')),

    # Public website pages (rendered by apps.pages)
    path('', include('apps.pages.urls')),

    # REST API (versioned)
    path('api/v1/', include('apps.api.v1.urls')),

    # Health check
    path('health/', include('apps.core.urls')),
]
```

This keeps the URL surface clean. Template-rendered views live under the
root/`auth/` namespace. The API is cleanly separated under `/api/v1/`. No business
app mounts its own URLs at the root level — all routing goes through `pages` or `api`.

---

## 8. Settings Architecture

A production-grade settings setup uses environment-based configuration, not
hardcoded values. The recommended structure:

```text
config/
├── settings/
│   ├── __init__.py        ← imports from base + env-selected module
│   ├── base.py            ← common settings (INSTALLED_APPS, MIDDLEWARE, etc.)
│   ├── development.py     ← DEBUG=True, console email, SQLite
│   ├── production.py      ← DEBUG=False, HTTPS, PostgreSQL, S3, SMTP
│   └── testing.py         ← fast password hasher, in-memory cache, test email
├── urls.py
├── wsgi.py
└── asgi.py
```

Environment-specific secrets (SECRET_KEY, DB credentials, API keys) are read from
environment variables via `python-decouple` or `django-environ`. Never committed to
version control.

---

## 9. Asynchronous Infrastructure

Financial and notification operations must not block web request cycles.

**Celery** is the task queue. **Redis** is the broker.

| Task category | App | Examples |
|---|---|---|
| Email delivery | `notifications` | `send_email_notification` |
| SMS delivery | `notifications` | `send_sms_notification` |
| Push delivery | `notifications` | `send_push_notification` |
| Rate fetching | `rates` | `fetch_fx_rates`, `fetch_crypto_prices` |
| KYC processing | `kyc` | `process_video_kyc` (future AI review) |
| Payment webhooks | `payments` | `process_provider_webhook` |
| Wallet reconciliation | `wallet` | `reconcile_wallet_balances` |
| Report generation | `core` | `generate_admin_report` |
| Token expiry cleanup | `accounts` | `expire_old_tokens` |

All Celery tasks that touch financial data must be idempotent and must log their
outcome in `AuditLog`.

---

## 10. Storage Architecture

| Data type | Storage | Access |
|---|---|---|
| Static assets (CSS, JS, images) | CDN-backed object storage | Public |
| User avatars | Object storage | Public (after KYC, pseudonymous path) |
| Order documents | Private object storage | Signed URL, audit-logged access |
| KYC documents | Private object storage, separate bucket | Signed URL, reviewer-only, audit-logged |
| Media uploads (blog/content) | Object storage | Public |
| Logs | Structured log sink (e.g., Elasticsearch / CloudWatch) | Internal |
| Backups | Separate account/bucket with retention policy | Internal |

KYC documents are stored in a bucket separated from all other storage and with
strict access policies. Signed URLs expire after a short window (e.g., 15 minutes).
Every access generates an `AuditLog` entry.

---

## 11. Scalability Considerations

### Database

- Use PostgreSQL. SQLite is only for local development.
- Add `db_index=True` to all FK fields used in list queries: `Order.user`, `Order.status`, `WalletTransaction.wallet`, `Notification.user`.
- `WalletTransaction` will be the largest table. Partition by date range once it exceeds ~10M rows.
- Use `select_related` and `prefetch_related` consistently; never N+1 queries in list views.
- Read replicas for reporting/admin queries as traffic grows.

### Caching

- Cache rate data aggressively (rates change at most every few minutes; most pages can serve 30-second cached snapshots).
- Cache `ServiceCategory` list (changes rarely, read very frequently).
- Cache per-user unread notification count.
- Use `django-cacheops` or manual `cache.get/set` with Redis for fine-grained per-object caching.
- Never cache wallet balances without an invalidation strategy — a stale balance causes trust problems.

### API

- All list endpoints paginated (no unbounded queries).
- Financial POST endpoints accept and enforce idempotency keys.
- Rate limiting per IP (anonymous) and per user (authenticated) at the `api` layer.
- DRF throttle classes configured per endpoint sensitivity.

### Async

- Long-running operations (KYC video processing, bulk notifications) are always async.
- Celery worker pools separated by queue: `default`, `financial`, `notifications`, `rates`.
  Financial tasks run on a dedicated worker to prevent queue starvation by notification bursts.

### Horizontal scaling

- The Django application is stateless (sessions in Redis, files in object storage) — adding
  more web workers is a single configuration change.
- Celery workers scale independently of web workers.
- Rate data can be served from a read-only replica to completely offload the write DB.

---

## 12. Migration from Current State

The current project has two apps: `pages` and `orders`. Both continue to exist.
The migration path from today to the full architecture is:

| Step | Action |
|---|---|
| 1 | Create `apps/` directory. Move `orders/` → `apps/orders/`, `pages/` → `apps/pages/`. Update `INSTALLED_APPS`. |
| 2 | Create `apps/core/`. Add `AuditLog`, `SiteConfiguration`, shared utilities. |
| 3 | Create `apps/accounts/` with custom `User` model. Set `AUTH_USER_MODEL`. Drop SQLite and remigrate fresh. |
| 4 | Create `apps/profiles/`. |
| 5 | Extend `apps/orders/` with `ServiceCategory`, `OrderStatusHistory`, authenticated user FK. |
| 6 | Create remaining apps (`kyc`, `wallet`, `payments`, `support`, `content`, `rates`, `notifications`) as empty shells with placeholder models first, then fill them phase by phase per the roadmap in `PRODUCT_SPEC.md`. |
| 7 | Create `apps/api/` with DRF infrastructure. Begin exposing endpoints. |
| 8 | Add `INSTALLED_APPS` entries and migration dependencies carefully; each new app must declare the correct `dependencies` in its `0001_initial.py`. |

Empty shell apps (placeholder `models.py` with a comment and a correct `AppConfig`)
are created early so that `INSTALLED_APPS` reflects the final structure from the
start. This prevents the need to rename app labels later, which is painful once
migrations are applied.

---

## 13. Third-Party Package Dependencies

| Package | Purpose | App |
|---|---|---|
| `djangorestframework` | REST API | `api` |
| `djangorestframework-simplejwt` | JWT authentication for API | `api`, `accounts` |
| `django-cors-headers` | CORS for Next.js frontend | `api` |
| `django-storages` + `boto3` | S3-compatible object storage | `kyc`, `orders`, `content` |
| `celery` | Async task queue | `notifications`, `rates`, `payments` |
| `redis` (python client) | Celery broker + Django cache | all |
| `django-celery-beat` | Periodic task scheduling | `rates` |
| `python-decouple` or `django-environ` | Environment-based settings | `config` |
| `psycopg2-binary` | PostgreSQL adapter | `config` |
| `argon2-cffi` | Password hashing upgrade | `accounts` |
| `Pillow` | Image processing (avatar, KYC preview) | `profiles`, `kyc` |
| `django-ratelimit` or custom | Rate limiting (auth, API) | `accounts`, `api` |

Packages are not yet installed. This list represents the target production dependency set.

---

*This document defines the target app structure and is the authoritative reference for
all future implementation work on JetPay24. Individual phase implementation plans
(like `PHASE1_AUTH_PLAN.md`) describe how each app is built; this document describes
how they all fit together.*
