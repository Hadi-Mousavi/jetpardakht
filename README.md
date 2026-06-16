# JetPay24

**JetPay24** (`جت‌پی‌۲۴`) is a Django-based web application for international payment services designed for students and families.

The project is actively under development and currently focuses on order submission, document upload, admin management, and public order tracking.

## Overview

JetPay24 helps users request international payment services through a simple Persian-language web interface. Users can submit payment orders, upload required documents, and track their order status using a public tracking code.

Current supported services include:

- University application fee payments
- University tuition payments
- TOEFL registration payments
- GRE registration payments
- International money transfers

## Features

- Persian landing page for JetPay24 services
- Order submission form
- Secure document upload validation
- Automatic public tracking code generation
- Public order tracking page
- Django admin panel for order management
- Admin search and filtering for orders
- Persian UI text and RTL layout

## Screenshots

Screenshots will be added as the UI stabilizes.

- Landing page
- Order submission page
- Order success page with tracking code
- Public tracking page
- Django admin order list

## Tech Stack

- Python 3.10+
- Django 4.2
- PostgreSQL 14+
- Bootstrap RTL
- Bootstrap Icons
- Vazirmatn Persian font

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd JetPay24
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
```

On Windows:

```bash
venv\Scripts\activate
```

On macOS/Linux:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` and set at minimum your PostgreSQL password:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=jetpay24
DB_USER=postgres
DB_PASSWORD=your-postgres-password
DB_HOST=localhost
DB_PORT=5432
```

To generate a secure `SECRET_KEY`, run:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5. Set up PostgreSQL

Ensure PostgreSQL is running, then create the database:

```bash
psql -U postgres -c "CREATE DATABASE jetpay24;"
```

Or using the `psql` interactive prompt:

```sql
CREATE DATABASE jetpay24;
```

### 6. Apply migrations

```bash
python manage.py migrate
```

### 7. Create an admin user

```bash
python manage.py createsuperuser
```

### 8. Start the development server

```bash
python manage.py runserver
```

## Local URLs

| Page | URL |
|---|---|
| Website | `http://127.0.0.1:8000/` |
| Order form | `http://127.0.0.1:8000/order/` |
| Order tracking | `http://127.0.0.1:8000/tracking/` |
| Admin panel | `http://127.0.0.1:8000/admin/` |

## Project Structure

```text
JetPay24/
├── config/                 # Django project settings and root URL configuration
├── orders/                 # Order model, forms, views, admin, URLs, migrations
├── pages/                  # Public landing page views and URLs
├── templates/
│   ├── orders/             # Order form, success, and tracking templates
│   └── pages/              # Landing page template
├── docs/                   # Architecture and planning documents
├── .env                    # Local environment variables (not committed)
├── .env.example            # Environment variable template (committed)
├── requirements.txt        # Python dependencies
├── manage.py               # Django management entry point
└── README.md
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | Django secret key |
| `DEBUG` | No | `False` | Enable debug mode |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `DB_NAME` | No | `jetpay24` | PostgreSQL database name |
| `DB_USER` | No | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | No | *(empty)* | PostgreSQL password |
| `DB_HOST` | No | `localhost` | PostgreSQL host |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `MEDIA_URL` | No | `/media/` | URL prefix for uploaded files |

## Future Roadmap

- Phase 1: User accounts and authentication
- Phase 2: Customer panel (dashboard, profile, settings)
- Phase 3: KYC identity verification
- Phase 4: Wallet and payment ledger
- Phase 5: Support tickets and live chat
- Phase 6: Blog, FAQ, and content management
- Phase 7: Exchange rates, USDT, and crypto price pages
- Phase 8: Bilingual support (Persian and English)
- Phase 9: Android and iOS mobile apps

## Development Status

JetPay24 is an active project under development. The current version is suitable for local development and feature iteration, but production deployment requires additional security, configuration, testing, and infrastructure work.
