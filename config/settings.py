"""
Django settings for JetPay24.
"""

import sys

from pathlib import Path

from decouple import Csv, config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # accounts must appear before any app that references AUTH_USER_MODEL
    'accounts',

    'orders',
    'pages',
    'kyc',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_ratelimit.middleware.RatelimitMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database — PostgreSQL
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
# ---------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='jetpay24'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': 60,
    }
}

# ---------------------------------------------------------------------------
# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# ---------------------------------------------------------------------------
# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# ---------------------------------------------------------------------------
# Static and media files
# https://docs.djangoproject.com/en/4.2/howto/static-files/
# ---------------------------------------------------------------------------

STATIC_URL = 'static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = config('MEDIA_URL', default='/media/')
MEDIA_ROOT = BASE_DIR / 'media'

# ---------------------------------------------------------------------------
# Private media — NEVER served directly by the web server.
# ---------------------------------------------------------------------------
# Order attachments and message attachments live under PRIVATE_MEDIA_ROOT,
# which is a sibling of MEDIA_ROOT and intentionally outside it.
#
# Security model:
#   - No nginx/Apache alias must exist for this directory.
#   - Django's static() helper in urls.py only serves MEDIA_ROOT, so
#     PRIVATE_MEDIA_ROOT is unreachable through /media/ in every environment.
#   - The only way to read a file is through the authenticated download views:
#       orders.views.order_attachment_download
#       orders.views.message_attachment_download
#
# Production checklist:
#   □ nginx has NO location block for private_media/
#   □ Apache has NO Alias directive for private_media/
#   □ DEBUG=False in production
#   □ PRIVATE_MEDIA_ROOT directory is NOT inside the document root
# ---------------------------------------------------------------------------
PRIVATE_MEDIA_ROOT = BASE_DIR / 'private_media'

# ---------------------------------------------------------------------------
# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# ---------------------------------------------------------------------------
# Rate limiting (django-ratelimit)
# ---------------------------------------------------------------------------
# Disabled automatically during `manage.py test` so the existing suite is
# unaffected.  Rate-limit tests opt in with @override_settings(RATELIMIT_ENABLE=True).

RATELIMIT_ENABLE = config(
    'RATELIMIT_ENABLE',
    default='test' not in sys.argv,
    cast=bool,
)
RATELIMIT_VIEW = 'config.ratelimit_handlers.ratelimited_error'

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
}
