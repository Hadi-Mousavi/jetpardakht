"""
Rate-limit tests for authentication endpoints.
"""

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.ratelimit_handlers import RATE_LIMIT_MESSAGE


@override_settings(RATELIMIT_ENABLE=True)
class AuthRateLimitTests(TestCase):
    """django-ratelimit protection on login, register, and OTP stubs."""

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_login_rate_limit_by_ip(self):
        url = reverse('login')
        data = {'email': 'nobody@test.com', 'password': 'wrong'}

        for _ in range(5):
            resp = self.client.post(url, data)
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, RATE_LIMIT_MESSAGE, status_code=429)

    def test_register_rate_limit_by_ip(self):
        url = reverse('register')

        for i in range(5):
            resp = self.client.post(url, {
                'first_name': 'Test',
                'last_name': 'User',
                'email': f'user{i}@test.com',
                'phone': f'0912000{i:04d}',
                'password1': 'ComplexPass123!',
                'password2': 'ComplexPass123!',
            })
            self.assertNotEqual(resp.status_code, 429)

        resp = self.client.post(url, {
            'first_name': 'Blocked',
            'last_name': 'User',
            'email': 'blocked@test.com',
            'phone': '09129999999',
            'password1': 'ComplexPass123!',
            'password2': 'ComplexPass123!',
        })
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, RATE_LIMIT_MESSAGE, status_code=429)

    def test_otp_request_rate_limit_by_ip(self):
        url = reverse('otp_request')

        for _ in range(3):
            resp = self.client.post(url)
            self.assertIn(resp.status_code, [501, 429])

        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()['error'], RATE_LIMIT_MESSAGE)

    def test_otp_resend_rate_limit_by_ip(self):
        url = reverse('otp_resend')

        for _ in range(3):
            resp = self.client.post(url)
            self.assertIn(resp.status_code, [501, 429])

        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()['error'], RATE_LIMIT_MESSAGE)

    def test_login_get_not_rate_limited(self):
        """GET requests to the login page must remain accessible."""
        for _ in range(10):
            resp = self.client.get(reverse('login'))
            self.assertEqual(resp.status_code, 200)
