import os
from wyze_sdk import Client

response = Client().login(
    email=os.environ['WYZE_EMAIL'],
    password=os.environ['WYZE_PASSWORD'],
    key_id=os.environ['WYZE_KEY_ID'],
    api_key=os.environ['WYZE_API_KEY']
)

print(f"access token: {response['access_token']}")
print(f"refresh token: {response['refresh_token']}")

client = Client(token=response['access_token'])

try:
    response = client.devices_list()
    for device in client.devices_list():
        print(f"mac: {device.mac}")
        print(f"nickname: {device.nickname}")
        print(f"is_online: {device.is_online}")
        print(f"product model: {device.product.model}")
except WyzeApiError as e:
    # You will get a WyzeApiError if the request failed
    print(f"Got an error: {e}")

client.plugs.turn_on(device_mac="D03F27A0A34A", device_model="WLPP1CFH")