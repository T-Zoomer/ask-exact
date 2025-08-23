# Exact Online OAuth 2.0 Integration

A Django application that implements OAuth 2.0 authentication for Exact Online, allowing secure access to Exact Online's REST API.

## Features

- Complete OAuth 2.0 authorization flow implementation
- Multi-country support (NL, BE, UK, FR, DE, US)
- Automatic token refresh handling
- Django admin integration for app and token management
- Easy-to-use service classes for API interactions
- Web interface for managing OAuth connections

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd ask-exact

# Install dependencies
pip3 install -r requirements.txt
# or using the dependencies from pyproject.toml:
pip3 install requests python-dotenv cryptography django
```

### 2. Django Setup

```bash
# Run migrations
python3 manage.py migrate

# Create superuser for admin access
python3 manage.py createsuperuser

# Start development server
python3 manage.py runserver
```

### 3. Configure Exact Online App

1. Visit Exact Online App Center: `https://apps.exactonline.com/be/nl-BE/V2/Manage`
2. Create a new app or use existing one
3. Set the OAuth redirect URI to: `http://127.0.0.1:8000/oauth/callback/`
4. Note your Client ID and Client Secret

### 4. Set Environment Variables

Create a `.env` file or set environment variables:

```bash
export EXACT_CLIENT_ID="your_client_id_here"
export EXACT_CLIENT_SECRET="your_client_secret_here"
export EXACT_COUNTRY="NL"  # Optional, defaults to NL
export EXACT_REDIRECT_URI="http://127.0.0.1:8000/oauth/callback/"  # Optional
```

## Usage

### Web Interface

1. Visit the OAuth manager: `http://127.0.0.1:8000/oauth/`
2. Click "Authorize Application" for your configured app
3. Complete the OAuth flow in Exact Online
4. Use the token to make API requests

### Programmatic Usage

```python
from exact_oauth.services import get_service

# Get service instance (user must be authenticated and have valid token)
service = get_service(request.user)

# Get accounts
accounts_response = service.get_accounts(top=50)
if accounts_response.status_code == 200:
    accounts = accounts_response.json()

# Get items
items_response = service.get_items(top=100)
if items_response.status_code == 200:
    items = items_response.json()

# Get sales invoices
invoices_response = service.get_sales_invoices()
if invoices_response.status_code == 200:
    invoices = invoices_response.json()

# Make custom API requests
response = service.get('crm/Accounts', params={'$filter': 'Name eq \'Test\''})
response = service.post('crm/Accounts', data={'Name': 'New Account'})
response = service.put('crm/Accounts(guid\'123\')', data={'Name': 'Updated Account'})
response = service.delete('crm/Accounts(guid\'123\')')
```

## API Endpoints

- `GET /oauth/` - View OAuth status and manage authorization
- `GET /oauth/authorize/` - Start OAuth authorization flow
- `GET /oauth/callback/` - OAuth callback endpoint
- `GET /oauth/refresh/` - Refresh token
- `POST /oauth/revoke/` - Revoke token
- `GET /oauth/test/` - Test API connection (JSON response)

## Configuration

### Settings

The following settings can be configured in your Django settings:

```python
# Exact Online OAuth Configuration
EXACT_OAUTH_SETTINGS = {
    'DEFAULT_REDIRECT_URI': 'http://127.0.0.1:8000/oauth/callback/',
    'TOKEN_REFRESH_THRESHOLD_MINUTES': 5,  # Refresh token when it expires within this time
}

# Login URLs for authentication
LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/oauth/'
LOGOUT_REDIRECT_URL = '/oauth/'
```

### Environment Variables

For production, consider using environment variables:

```bash
# .env file
EXACT_CLIENT_ID=your_client_id
EXACT_CLIENT_SECRET=your_client_secret
DJANGO_SECRET_KEY=your_django_secret_key
```

## Models

### ExactOnlineApp
Stores OAuth app configurations including client credentials and country settings.

### ExactOnlineToken  
Stores OAuth tokens for users, including access tokens, refresh tokens, and expiration info.

### ExactOnlineAuthState
Temporary storage for OAuth state parameters during the authorization flow.

## Important Notes

### Token Refresh Behavior
- Exact Online tokens expire every 10 minutes
- Refresh tokens are invalidated when used and replaced with new ones
- The service automatically refreshes tokens when they're about to expire
- Always update both access and refresh tokens when refreshing

### Country-Specific URLs
Different countries use different base URLs:
- Netherlands: `https://start.exactonline.nl`
- Belgium: `https://start.exactonline.be` 
- UK: `https://start.exactonline.co.uk`
- France: `https://start.exactonline.fr`
- Germany: `https://start.exactonline.de`
- US: `https://start.exactonline.com`

### Security Considerations
- Store client secrets securely
- Use HTTPS in production
- Implement proper session management
- Monitor token usage and refresh patterns

## Troubleshooting

### Common Issues

1. **"No valid token found"**
   - Ensure the user has authorized the app
   - Check if the token has expired
   - Verify app configuration in admin

2. **"Failed to refresh token"**
   - Check client credentials
   - Verify the app is still active in Exact Online
   - Ensure the user hasn't revoked access

3. **"Could not determine base server URI"**
   - The initial API call to get user info failed
   - Check token validity
   - Verify network connectivity

### Debug Mode

Enable Django debug mode to see detailed error messages:

```python
# settings.py
DEBUG = True
```

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License.