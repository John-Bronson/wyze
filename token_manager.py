import os
from datetime import datetime, timedelta
from typing import Mapping
# Import the load_dotenv function
from dotenv import load_dotenv
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError

# Load environment variables from the .env file
load_dotenv()

class TokenManager:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.client = None
        # Now, these will be correctly populated after load_dotenv() runs
        self._email = os.environ.get('WYZE_EMAIL')
        self._password = os.environ.get('WYZE_PASSWORD')
        self._key_id = os.environ.get('WYZE_KEY_ID')
        self._api_key = os.environ.get('WYZE_API_KEY')

    def _login(self):
        """Performs full login to get new tokens"""
        print("Performing a new login to Wyze...")
        try:
            login_response = Client().login(
                email=self._email,
                password=self._password,
                key_id=self._key_id,
                api_key=self._api_key
            )
            self._update_tokens_and_client(login_response)
        except WyzeApiError as e:
            print(f"Login failed: {e}")
            raise

    def _refresh(self):
        """Refreshes the access token using the refresh token"""
        print("Refreshing the access token...")
        try:
            temp_client = Client(token=self.access_token)
            # Corrected this call to pass the refresh token
            refresh_response = temp_client.refresh_token(self.refresh_token)
            self._update_tokens_and_client(refresh_response)
        except WyzeApiError as e:
            print(f"Token refresh failed: {e}")
            self._login()

    def _update_tokens_and_client(self, token_data: Mapping):
        """Updates the internal token data and the client instance"""
        self.access_token = token_data['access_token']
        self.refresh_token = token_data['refresh_token']
        expires_in = token_data.get('expires_in', 3600)
        self.expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.client = Client(token=self.access_token)
        print("Tokens updated successfully.")

    def is_token_expired(self) -> bool:
        """Checks if the access token is missing or expired (with a 5-min buffer)"""
        if not self.access_token or not self.expires_at:
            return True
        return datetime.now() >= self.expires_at - timedelta(minutes=5)

    def get_client(self) -> Client:
        """The main method to get a valid and authenticated client."""
        if self.is_token_expired():
            if self.refresh_token:
                self._refresh()
            else:
                self._login()
        return self.client

# Single, global instance for the app to use
token_manager = TokenManager()

if __name__ == "__main__":
    print("Running token_manager.py as a standalone script for testing...")
    try:
        wyze_client = token_manager.get_client()
        print(f"Access token: {token_manager.access_token}")
        print(f"Refresh token: {token_manager.refresh_token}")

        # Adding a check to ensure we got a client and devices
        if wyze_client:
            devices = wyze_client.devices_list()
            if devices:
                for device in devices:
                    print(f"  - {device.nickname} ({device.mac}) is {'online' if device.is_online else 'offline'}")
            else:
                print("No devices found on the account.")

        print("\nRequesting client again (should use existing token)...")
        wyze_client_2 = token_manager.get_client()
        if token_manager.client is wyze_client_2:
            print("Successfully reused existing client instance.")

    except (WyzeApiError, ValueError) as e:
        print(f"An error occurred during the test run: {e}")
