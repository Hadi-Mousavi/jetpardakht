# Phase 1: Identity & Authentication — Implementation Plan

**Project:** JetPay24  
**Phase:** 1 — Accounts & Authentication  
**Status:** Plan only — no code has been written  
**Prerequisite reading:** `docs/PRODUCT_SPEC.md`

---

## 1. Situation Analysis

### What exists today

| Area | Current state | Impact on this phase |
|---|---|---|
| User model | Django's built-in `auth.User` (not customized) | **Critical:** Must switch to a custom model before any auth migration is applied. Once data exists in `auth_user`, changing models is very painful. Now is the right time — no registered users yet. |
| `AUTH_USER_MODEL` | Not set → defaults to `auth.User` | Must be set to `accounts.User` before the first migration of the new app. |
| `Order` model | Has `name`, `phone`, `email` as plain fields (guest-style) | No FK to User today; linking will be a later step, not part of Phase 1. |
| Settings | `SECRET_KEY` hardcoded, `DEBUG=True`, `ALLOWED_HOSTS=["*"]` | Phase 1 must lay the groundwork for env-based settings. |
| Email | No email backend configured | Must add at minimum a console/file backend for dev and an SMTP setting stub for production. |
| Templates | Flat files, inline CSS, no base template | Phase 1 will introduce a shared base layout. |
| URLs | Two app includes (`pages`, `order`) + one direct view (`tracking`) | `accounts` will get its own include at `auth/`. |

### What Phase 1 must deliver

- Custom `User` model replacing Django's default, with all fields needed now and stubs for future expansion.
- `EmailVerificationToken` model for account activation links.
- `PasswordResetToken` model for password reset links.
- `OTPCode` model stub, dormant but structurally ready for future mobile OTP.
- Full registration → email-verify → login → logout → forgot-password → reset-password flow.
- Persian UI templates consistent with the existing site style.
- Settings changes and email backend wiring.
- `accounts` app registered and migration applied before any other migration touches the user table.

---

## 2. New App: `accounts`

### Directory structure

```text
accounts/
├── __init__.py
├── apps.py
├── admin.py
├── models.py
├── managers.py
├── forms.py
├── views.py
├── urls.py
├── tokens.py
├── emails.py
├── validators.py
└── migrations/
    └── 0001_initial.py

templates/
└── accounts/
    ├── register.html
    ├── register_done.html
    ├── login.html
    ├── email_verification_sent.html
    ├── email_verify_confirm.html
    ├── password_reset_request.html
    ├── password_reset_sent.html
    ├── password_reset_confirm.html
    ├── password_reset_done.html
    └── emails/
        ├── verify_email_subject.txt
        ├── verify_email_body.txt
        ├── verify_email_body.html
        ├── password_reset_subject.txt
        ├── password_reset_body.txt
        └── password_reset_body.html
```

---

## 3. Models

### 3.1 `User` (custom, replaces `auth.User`)

This is the most important architectural decision in Phase 1. Django's default `User` uses `username` as the login identifier and splits the name into `first_name`/`last_name` but doesn't have a `phone` field. A custom model is required.

**Base class:** `AbstractBaseUser` + `PermissionsMixin`  
Using `AbstractBaseUser` directly (rather than `AbstractUser`) gives full control over required fields, removing `username` entirely.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` (PK) | Default, inherited. |
| `email` | `EmailField`, unique | Primary login identifier. Must be stored lowercase-normalized. |
| `phone` | `CharField(max_length=20)`, unique, nullable | Optional at registration (Phase 1), required for OTP login (future). Stored as E.164 format where possible. |
| `first_name` | `CharField(max_length=60)` | Required at registration. |
| `last_name` | `CharField(max_length=60)` | Required at registration. |
| `is_active` | `BooleanField(default=False)` | **False until email is verified.** Unverified users cannot log in. |
| `is_staff` | `BooleanField(default=False)` | Admin panel access. |
| `is_email_verified` | `BooleanField(default=False)` | Explicit flag, separate from `is_active`. Allows future distinction (e.g., suspended account vs unverified account). |
| `is_phone_verified` | `BooleanField(default=False)` | False in Phase 1; activated when OTP phone flow is implemented. |
| `date_joined` | `DateTimeField(auto_now_add=True)` | Account creation timestamp. |
| `last_login` | `DateTimeField(null=True)` | Managed by Django's auth backend. |

**Why `is_active=False` by default:** Django's `authenticate()` and `login()` both check `is_active`. Setting it to `False` on creation means unverified users are blocked at the auth layer automatically, without any custom guard in views.

**`USERNAME_FIELD = 'email'`**  
**`REQUIRED_FIELDS = ['first_name', 'last_name']`** (used by `createsuperuser`)

**Fields deliberately omitted for now:** avatar, preferred language, address — those belong in a future `Profile` model (Phase 2, customer panel).

---

### 3.2 `UserManager`

Django's default `UserManager` creates users with a `username`. A custom manager is required to:

- Accept `email` as the unique identifier.
- Normalize (lowercase) email before saving.
- Provide `create_user(email, password, first_name, last_name, ...)` and `create_superuser(...)` methods.

The manager lives in `accounts/managers.py` and is assigned to `User.objects`.

---

### 3.3 `EmailVerificationToken`

**Purpose:** Stores a short-lived signed token used in the email-verification link.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` (PK) | |
| `user` | `ForeignKey(User, on_delete=CASCADE)` | Cascades on user delete. |
| `token` | `CharField(max_length=64)`, unique | A random URL-safe token (see §8 tokens). |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `expires_at` | `DateTimeField` | Set to `now + 24 hours` at creation. |
| `consumed_at` | `DateTimeField(null=True)` | Set when used. |

**Why store the token in the database rather than using Django's `PasswordResetForm` signing approach:** It allows explicit expiry control, one-time-use enforcement via `consumed_at`, easy revocation (delete the row), and a clear audit trail. The alternative (HMAC signing with `TimestampSigner`) is valid but doesn't allow single-use enforcement without a consumed flag somewhere.

**Business rules:**
- A user may only have one active (unconsumed, unexpired) token at a time. On re-send, the old token is deleted and a new one is created.
- Expired tokens are ignored silently; the user is prompted to request a new link.

---

### 3.4 `PasswordResetToken`

**Purpose:** Stores a short-lived token used in the password-reset email link.

**Fields:** identical structure to `EmailVerificationToken` — `user`, `token`, `created_at`, `expires_at`, `consumed_at`.

**Expiry:** 1 hour (shorter than email verification because a password-reset link is more sensitive).

**Business rules:**
- Same one-at-a-time rule; old token is invalidated when a new one is requested.
- On successful password reset: token is consumed AND all existing Django sessions for that user are invalidated (`update_session_auth_hash` or manual session flush).

---

### 3.5 `OTPCode` (Phase 1 stub, not yet used in UI)

**Purpose:** Prepared now so the database is ready for mobile OTP login in a future phase without a disruptive migration.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` (PK) | |
| `user` | `ForeignKey(User, null=True)` | Nullable: OTP may be for an unknown user (registration via phone). |
| `phone` | `CharField(max_length=20)` | Always present; used to look up target when user is null. |
| `code_hash` | `CharField(max_length=128)` | **Never store raw OTP codes.** Hash with PBKDF2/bcrypt. |
| `purpose` | `CharField` with choices: `LOGIN`, `REGISTER`, `PHONE_VERIFY`, `PASSWORD_RESET` | Prevents token reuse across flows. |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `expires_at` | `DateTimeField` | TTL 5–10 minutes. |
| `consumed_at` | `DateTimeField(null=True)` | |
| `attempt_count` | `PositiveSmallIntegerField(default=0)` | Rate-limit brute force. |

This model is created in the migration but has no view wiring in Phase 1.

---

## 4. Settings Changes Required

The following changes must be applied to `config/settings.py` before the first migration of the `accounts` app.

### 4.1 `AUTH_USER_MODEL`

```
AUTH_USER_MODEL = 'accounts.User'
```

**This is the single most important setting in Phase 1.** It must be present before `python manage.py migrate` is run with the new app. Django bakes this reference into all foreign keys to the user table (including Django's own `auth`, `sessions`, and `admin` apps). Changing it after migrations exist causes a complex, error-prone migration dependency chain.

**Action required before migration:**
1. Drop `db.sqlite3` (the dev database — no real user data exists).
2. Add `AUTH_USER_MODEL = 'accounts.User'` to settings.
3. Add `'accounts'` to `INSTALLED_APPS` above `django.contrib.admin`.
4. Run `python manage.py makemigrations accounts`.
5. Run `python manage.py migrate` (fresh).

### 4.2 `INSTALLED_APPS` order

```
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    ...
    'accounts',   ← must appear before apps that reference the user
    'orders',
    'pages',
]
```

### 4.3 Email backend

For development, use the console backend so emails print to the terminal without needing an SMTP server:

```
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

For production, environment variables will supply SMTP credentials:

```
EMAIL_BACKEND   = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST      = env('EMAIL_HOST')
EMAIL_PORT      = env('EMAIL_PORT', default=587)
EMAIL_USE_TLS   = True
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = 'JetPay24 <no-reply@jetpay24.ir>'
```

### 4.4 Auth redirect settings

```
LOGIN_URL          = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'      ← customer panel (future)
LOGOUT_REDIRECT_URL = '/'
```

### 4.5 Session security

```
SESSION_COOKIE_HTTPONLY = True    # prevents JS access to session cookie
SESSION_COOKIE_SAMESITE = 'Lax'   # CSRF mitigation
# SESSION_COOKIE_SECURE = True    # enable in production (HTTPS only)
```

### 4.6 Password validators

Keep all four existing validators and add a minimum-length configuration with a slightly higher threshold (8 characters minimum is the modern baseline):

```python
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': '...UserAttributeSimilarityValidator'},
    {'NAME': '...MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': '...CommonPasswordValidator'},
    {'NAME': '...NumericPasswordValidator'},
]
```

---

## 5. URLs

### 5.1 Mount in `config/urls.py`

Add one line:
```
path('auth/', include('accounts.urls')),
```

### 5.2 `accounts/urls.py`

| URL pattern | View name | Purpose |
|---|---|---|
| `auth/register/` | `register` | Registration form |
| `auth/register/done/` | `register_done` | Post-registration confirmation page |
| `auth/verify-email/<token>/` | `verify_email` | Email verification link target |
| `auth/resend-verification/` | `resend_verification` | Request a new verification email |
| `auth/login/` | `login` | Login form |
| `auth/logout/` | `logout` | POST-only logout |
| `auth/password/reset/` | `password_reset_request` | Enter email to receive reset link |
| `auth/password/reset/sent/` | `password_reset_sent` | Confirmation that email was sent |
| `auth/password/reset/<token>/` | `password_reset_confirm` | Enter new password |
| `auth/password/reset/done/` | `password_reset_done` | Success after reset |

**Notes:**
- No `auth/otp/` URLs in Phase 1 — the routes will be added later when the OTP flow is built.
- `logout` is POST-only to prevent CSRF-based logout via GET link (important security detail).
- All URLs under `auth/` are accessible to unauthenticated users except `resend_verification`, which requires a session hint (the unverified user's ID stored in session after registration).

---

## 6. Forms

### 6.1 `RegistrationForm`

Extends `forms.Form` (not `ModelForm`) so field validation and password hashing are fully controlled.

**Fields:**
- `first_name` — `CharField`, required, max 60 chars.
- `last_name` — `CharField`, required, max 60 chars.
- `email` — `EmailField`, required, validated against `User.objects.filter(email=...)` for uniqueness.
- `phone` — `CharField`, optional, custom `clean_phone()` validator checks Iranian mobile format (`09XXXXXXXXX`, 11 digits starting with 09).
- `password` — `CharField` with `PasswordInput`, required.
- `password_confirm` — `CharField` with `PasswordInput`, required. `clean()` checks both match.

**`clean_email()`:** normalizes to lowercase; raises `ValidationError` if already registered.

**`clean_phone()`:** optional field; if provided, validates format; raises `ValidationError` if already registered.

**`save()`:** calls `User.objects.create_user(...)` and returns the new user. Does not activate the user (that happens via email verification).

---

### 6.2 `LoginForm`

Extends `forms.Form`.

**Fields:**
- `email` — `EmailField`.
- `password` — `CharField` with `PasswordInput`.
- `remember_me` — `BooleanField`, optional. Controls session expiry.

**`clean()`:** calls `authenticate(request, email=..., password=...)`. If authentication fails, raises a generic `ValidationError` (do not distinguish between "wrong email" and "wrong password" — prevents user enumeration). If the user exists but `is_email_verified` is False, raise a distinct error that the view can use to offer the re-send link.

---

### 6.3 `PasswordResetRequestForm`

**Fields:**
- `email` — `EmailField`.

**Behavior:** Always shows a success message regardless of whether the email exists, preventing user enumeration through the password-reset endpoint.

---

### 6.4 `SetNewPasswordForm`

**Fields:**
- `password` — `CharField` with `PasswordInput`.
- `password_confirm` — `CharField` with `PasswordInput`.

Runs Django's `validate_password()` against the new password.

---

## 7. Views

All views are function-based to stay consistent with the existing codebase. Class-based views can be introduced in a later refactor.

### 7.1 `register`

```
GET  → render RegistrationForm
POST → validate form
       if valid:
         create User (is_active=False, is_email_verified=False)
         store user.id in session['pending_user_id'] (for resend flow)
         call send_verification_email(user)
         redirect to register_done
       if invalid:
         re-render form with errors
```

**Security:** The new user's `pk` is stored in the session so the resend view knows who to resend to without exposing the user ID in the URL.

---

### 7.2 `register_done`

```
GET → render confirmation page ("check your email")
      include a "resend email" link
```

No logic. Just a static informational page.

---

### 7.3 `verify_email`

```
GET → look up EmailVerificationToken by token string
      if not found or consumed:
        render error page ("link invalid or already used")
      if expired:
        render error page with "request new link" CTA
      if valid:
        mark token consumed_at = now
        set user.is_email_verified = True
        set user.is_active = True
        save user
        log the user in (call login(request, user))
        redirect to LOGIN_REDIRECT_URL
```

**Note:** The user is immediately logged in after verification — this is the standard, most user-friendly UX (avoids making the user log in immediately after just verifying).

---

### 7.4 `resend_verification`

```
POST only
     read session['pending_user_id']
     if missing: redirect to register
     load User, check is_email_verified is False
     delete old token
     create new token
     send email
     redirect to register_done (same page, shows "sent again" flash message)
```

**Rate limit consideration:** Wrap in a check that the last token was created at least 60 seconds ago before sending a new one, to prevent email bombing.

---

### 7.5 `login_view`

```
GET  (authenticated) → redirect to LOGIN_REDIRECT_URL
GET  (anonymous)     → render LoginForm
POST → validate LoginForm
       if form has auth error:
         re-render with error
         if error reason is "unverified": show special message + resend link
       if valid:
         if remember_me: set session to 2 weeks; else browser-session only
         call Django login(request, user)
         redirect to 'next' param or LOGIN_REDIRECT_URL
```

**`next` parameter handling:** Only accept internal relative URLs for the `next` redirect to prevent open redirect attacks. Use Django's `is_safe_url` / `url_has_allowed_host_and_scheme`.

---

### 7.6 `logout_view`

```
POST only (CSRF protected)
     call Django logout(request)
     redirect to LOGOUT_REDIRECT_URL
```

---

### 7.7 `password_reset_request`

```
GET  → render PasswordResetRequestForm
POST → validate email field
       (always show success page regardless of whether email exists)
       if User with email exists and is_email_verified:
         delete old PasswordResetToken for this user
         create new PasswordResetToken (TTL 1 hour)
         send password reset email
       redirect to password_reset_sent
```

---

### 7.8 `password_reset_sent`

Static confirmation page. No logic.

---

### 7.9 `password_reset_confirm`

```
GET  → look up PasswordResetToken by token string
       if invalid/consumed/expired: render error page
       if valid: render SetNewPasswordForm
POST → validate SetNewPasswordForm
       if valid:
         set user.password via set_password()
         save user
         mark token consumed
         call update_session_auth_hash(request, user) to keep them logged in
         (or flush all sessions if prefer forced re-login)
         redirect to password_reset_done
       if invalid: re-render form with errors
```

---

### 7.10 `password_reset_done`

Static success page with a login link.

---

## 8. Tokens (`accounts/tokens.py`)

A dedicated module handles token generation and lookup rather than scattering this logic through views.

### 8.1 Generation

Use `secrets.token_urlsafe(48)` to produce a 64-character URL-safe token. `secrets` is the correct standard library module for security-sensitive tokens (unlike `random`, which is not cryptographically secure).

### 8.2 Storage

The raw token string is stored in the database. Unlike password hashing, verification tokens do not need to be hashed because:

- They are single-use and short-lived.
- The database is a trusted server-side store (not shared with the client).
- Hashing them would require a constant-time comparison to prevent timing attacks anyway.

If you prefer defense-in-depth: hash the token with `hashlib.sha256` before storage, and hash the incoming token before the DB lookup. This way a DB breach doesn't expose usable tokens.

### 8.3 Helper functions (to be implemented in `tokens.py`)

- `create_email_verification_token(user)` → creates, saves, returns token string.
- `verify_email_token(token_string)` → returns `(user, error_code)` where error codes are `VALID`, `NOT_FOUND`, `EXPIRED`, `CONSUMED`.
- `create_password_reset_token(user)` → creates, saves, returns token string.
- `verify_password_reset_token(token_string)` → returns `(user, error_code)`.

---

## 9. Emails (`accounts/emails.py`)

A dedicated module for composing and sending auth emails. This isolates email logic from views and makes it testable independently.

### 9.1 `send_verification_email(user, token_string, request)`

Composes a multipart email (plain text + HTML) using Django templates:

- **Subject:** rendered from `accounts/emails/verify_email_subject.txt`.
- **Body (text):** rendered from `accounts/emails/verify_email_body.txt`.
- **Body (HTML):** rendered from `accounts/emails/verify_email_body.html`.

Template context includes: `user.first_name`, the full verification URL, and the token expiry duration.

The verification URL is built as: `{scheme}://{host}/auth/verify-email/{token}/`

The `request` object is passed in to correctly build the absolute URL (handles dev vs. production domains).

### 9.2 `send_password_reset_email(user, token_string, request)`

Same pattern, different templates. Subject and body are in Persian.

### 9.3 Future proofing

In Phase 1, emails are sent synchronously inside the request/response cycle. For production, this should move to a Celery task (or Django's `send_mail` with a queue). The `emails.py` module is already isolated, so the only change needed later is to wrap the calls in a task.

---

## 10. Validators (`accounts/validators.py`)

A small module for reusable field validators that don't belong in the form alone.

### `validate_iranian_phone(value)`

Validates that the phone number matches the pattern `^09[0-9]{9}$` (Iranian mobile numbers). Used in the form and can be attached to `User.phone` as a `validators=[...]` argument to also validate via the admin.

---

## 11. Admin Registration (`accounts/admin.py`)

Registering the custom `User` in the admin requires a custom `UserAdmin` that extends `django.contrib.auth.admin.UserAdmin`.

Key changes from the default:
- `list_display`: `email`, `first_name`, `last_name`, `phone`, `is_active`, `is_email_verified`, `date_joined`.
- `ordering`: `('-date_joined',)`.
- `search_fields`: `('email', 'first_name', 'last_name', 'phone')`.
- `list_filter`: `('is_active', 'is_email_verified', 'is_staff', 'date_joined')`.
- Remove `username` from all fieldsets; replace with `email`.
- Add `phone`, `is_email_verified`, `is_phone_verified` to the appropriate fieldset.
- `add_fieldsets`: the form shown when creating a user in the admin.

`EmailVerificationToken` and `PasswordResetToken` should also be registered as read-only admin views (for debugging / support purposes), with `consumed_at`, `expires_at` visible but no ability to generate new tokens from the admin.

---

## 12. Templates

### 12.1 Base template

Phase 1 is the right time to introduce `templates/base.html` — a shared layout that all pages extend. The current templates each duplicate the full HTML boilerplate, CDN imports, and navbar. A base template solves this:

```text
templates/
└── base.html        ← new; shared layout, navbar, footer, CDN imports
```

Blocks to define in `base.html`:
- `{% block title %}` — page title.
- `{% block extra_head %}` — per-page extra CSS.
- `{% block content %}` — main page body.
- `{% block extra_scripts %}` — per-page extra JS.

Existing templates (`home.html`, `order_create.html`, etc.) should be refactored to extend `base.html` at the same time. This is a template-only change with no business logic impact.

---

### 12.2 Auth template notes

All auth templates extend `base.html` and use the existing Bootstrap RTL + Vazirmatn font stack.

**`register.html`**
- Fields: نام، نام خانوادگی، ایمیل، موبایل (اختیاری)، رمز عبور، تکرار رمز عبور.
- Password strength visual hint.
- Link to login page below the form.

**`login.html`**
- Fields: ایمیل، رمز عبور.
- "Remember me" checkbox.
- Links: "فراموشی رمز عبور" (password reset) and "ثبت‌نام" (register).
- If the user was redirected here from a protected page, show a message like: "برای ادامه ابتدا وارد شوید."
- If the error is "email not verified", show a specific message with a "ارسال مجدد ایمیل تأیید" link.

**`register_done.html`** and **`email_verification_sent.html`**
- Confirmation that the email was sent.
- Clear instruction: check inbox and spam folder.
- "ارسال مجدد" (resend) button (POST form, CSRF token).

**`email_verify_confirm.html`**
- Success: "ایمیل شما با موفقیت تأیید شد" + auto-redirect notice.
- Error states: expired link, already used link — each with a distinct, helpful Persian message.

**`password_reset_request.html`**
- Single email field.
- Note: "لینک بازیابی به ایمیل شما ارسال خواهد شد."

**`password_reset_confirm.html`**
- Two password fields (new password + confirm).
- Show Django's password rules in Persian.

**Email body templates**
- Plain text versions are mandatory (not all email clients render HTML).
- HTML versions should be clean inline-styled HTML (email clients don't support external CSS).
- All text in Persian.
- Include the JetPay24 brand name and a disclaimer: "اگر این درخواست توسط شما ارسال نشده، این ایمیل را نادیده بگیرید."

---

## 13. Migrations

### 13.1 Order of operations — critical

The migration for the `accounts` app must be the **first** migration to define the user table. This must happen before `django.contrib.admin`, `django.contrib.auth`, or any other app that has a FK to the user model runs its own migrations.

Because Django handles this through migration dependencies automatically (once `AUTH_USER_MODEL` is set correctly), the order of `makemigrations` calls matters:

1. Set `AUTH_USER_MODEL = 'accounts.User'` in settings.
2. Add `'accounts'` to `INSTALLED_APPS`.
3. Drop `db.sqlite3`.
4. Run `python manage.py makemigrations accounts` → creates `accounts/0001_initial.py`.
5. Run `python manage.py migrate` → applies all migrations in dependency order.

### 13.2 Migration file: `accounts/0001_initial.py`

This single migration creates four tables:

- `accounts_user` — the custom user table.
- `accounts_emailverificationtoken`.
- `accounts_passwordresettoken`.
- `accounts_otpcode` — empty but structurally present for future use.

It also carries the `AUTH_USER_MODEL` reference that connects Django's built-in permission and session tables to `accounts_user` instead of `auth_user`.

### 13.3 `orders` app impact

The existing `Order` model references `email`, `phone`, and `name` as plain strings. These do not need to change in Phase 1 — the orders flow currently works without a logged-in user, and linking orders to user accounts is a Phase 2 concern. No new migration is needed for `orders` as part of Phase 1.

---

## 14. Security Considerations

### 14.1 User enumeration prevention

Both the login form and the password-reset form must not reveal whether a given email address is registered:

- Login error: "ایمیل یا رمز عبور اشتباه است." — do not say "این ایمیل ثبت نشده."
- Password reset: always show "اگر این ایمیل در سیستم ما ثبت شده باشد، لینک بازیابی ارسال شد." regardless of outcome.

### 14.2 Token security

- Generate tokens with `secrets.token_urlsafe()`, not `random` or `uuid4`.
- Tokens are single-use (`consumed_at` is set on first valid use).
- Tokens are short-lived (24h for email verification, 1h for password reset).
- On re-request, old tokens are deleted, not reused.

### 14.3 Rate limiting

Phase 1 should implement basic rate limits on high-risk endpoints using a simple per-IP counter stored in the Django cache (or in the database if no cache is configured yet):

- **Registration:** max 5 registrations per IP per hour.
- **Login:** max 10 failed attempts per IP per 15 minutes. After 5 consecutive failures for a specific email, add a 30-second delay.
- **Resend verification:** max 3 resends per user per hour.
- **Password reset request:** max 3 requests per email per hour.

A full implementation uses Django's cache framework. A simpler Phase 1 approach: use a database-backed counter model, or integrate `django-ratelimit` (a well-maintained third-party package).

### 14.4 CSRF

All POST forms must include `{% csrf_token %}`. The `logout` endpoint being POST-only is specifically a CSRF defence: a third-party site cannot log a user out by embedding an `<img>` or `<a>` tag.

### 14.5 Password security

Django's `PBKDF2PasswordHasher` (the default) is acceptable. For higher security in production, switch to `Argon2PasswordHasher` (requires `argon2-cffi` library). This is a one-setting change and does not require a data migration — existing passwords remain valid and are re-hashed on next login.

Add to settings (production):
```
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',  # fallback for existing
]
```

### 14.6 Session fixation

After a successful login, Django's `login()` automatically cycles the session ID, preventing session fixation attacks. No extra work needed — but confirm `SESSION_COOKIE_HTTPONLY = True` and `SESSION_COOKIE_SAMESITE = 'Lax'` are set.

### 14.7 Email link safety

Verification and reset links must use HTTPS in production. In development, HTTP is acceptable. Build links from the request object (`request.build_absolute_uri`) rather than hardcoding the domain.

### 14.8 `is_active` vs `is_email_verified`

Keeping both flags is intentional:

- `is_active=False` → blocks all login attempts at the Django auth layer.
- `is_email_verified=False` → semantically records why `is_active` is False at creation, and allows future distinctions (e.g., a verified user can be deactivated by an admin without losing the verified status on record).

---

## 15. Future Extensibility

### 15.1 OTP login (mobile)

The `OTPCode` model is created in this phase but wired to nothing. When Phase 2 adds OTP login:

- Add views and URLs under `auth/otp/`.
- Add `phone` field validation as a registration step.
- The `User.phone` field and `User.is_phone_verified` flag are already in the schema.
- No new migration column additions needed.

### 15.2 REST API / mobile app

When the `panel.jetpay24.com` frontend (Next.js) or mobile apps consume the backend via DRF:

- Add `djangorestframework` and `djangorestframework-simplejwt` to the project.
- Create an `api/` app (or `accounts/api/` submodule) with serializers and token views.
- The `User` model requires no changes — DRF works with any `AUTH_USER_MODEL`.
- JWT access tokens are short-lived (15 minutes); refresh tokens are long-lived and stored server-side or in an `HttpOnly` cookie.

### 15.3 Social / OAuth login

If Google/Apple sign-in is added later:

- Add `django-allauth` or build a custom OAuth2 callback view.
- `User.email` remains the canonical identifier.
- Social accounts link to existing Users by email or via a separate `SocialAccount` model.

### 15.4 Two-factor authentication (2FA)

Phase 1 lays no 2FA groundwork beyond the `OTPCode` model, but the architecture supports adding TOTP (authenticator app) later:

- Add `totp_secret` to `User` or a linked model.
- Add a 2FA verification step in the login view after password check.

### 15.5 `panel.jetpay24.com` subdomain

The auth flow described here works on the same domain (`jetpay24.com/auth/`). When the customer panel moves to a separate subdomain, two options exist:

- **Option A (recommended for Next.js SPA):** Move auth to the DRF API with JWT; the Next.js app stores the access token in memory and refresh token in an `HttpOnly` cookie.
- **Option B (Django session on subdomain):** Share the session cookie across subdomains via `SESSION_COOKIE_DOMAIN = '.jetpay24.com'`. Simpler but only works with server-rendered Django templates.

The Phase 1 session-based auth is Option B-compatible by default. Option A requires adding DRF + JWT in a future phase but shares all the same `User` model and business logic.

---

## 16. Implementation Checklist

This checklist reflects the correct order of implementation to avoid dependency issues.

- [ ] Update `config/settings.py`: set `AUTH_USER_MODEL`, email backend, session settings, update password validators, add login URLs.
- [ ] Create `accounts/` directory with `__init__.py` and `apps.py`.
- [ ] Add `'accounts'` to `INSTALLED_APPS`.
- [ ] Write `accounts/managers.py` — `UserManager`.
- [ ] Write `accounts/models.py` — `User`, `EmailVerificationToken`, `PasswordResetToken`, `OTPCode`.
- [ ] Write `accounts/validators.py` — `validate_iranian_phone`.
- [ ] Drop `db.sqlite3`, run `makemigrations accounts`, run `migrate`.
- [ ] Verify Django system check passes with `python manage.py check`.
- [ ] Write `accounts/tokens.py` — `create_*_token` and `verify_*_token` helpers.
- [ ] Write `accounts/emails.py` — `send_verification_email`, `send_password_reset_email`.
- [ ] Create email body templates under `templates/accounts/emails/`.
- [ ] Write `accounts/forms.py` — `RegistrationForm`, `LoginForm`, `PasswordResetRequestForm`, `SetNewPasswordForm`.
- [ ] Write `accounts/views.py` — all ten views.
- [ ] Write `accounts/urls.py`.
- [ ] Add `path('auth/', include('accounts.urls'))` to `config/urls.py`.
- [ ] Write `accounts/admin.py`.
- [ ] Create `templates/base.html` and refactor existing templates to extend it.
- [ ] Create all auth templates under `templates/accounts/`.
- [ ] Add "ورود / ثبت‌نام" link to the main site navbar (`home.html`).
- [ ] Write tests: `accounts/tests.py` — registration, email verification, login, logout, password reset.
- [ ] Manual end-to-end test of full flow in browser.
- [ ] Verify `python manage.py check --deploy` output and resolve any warnings.
