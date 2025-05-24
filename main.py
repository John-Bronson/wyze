from flask import Flask, redirect, url_for
import os
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Validate required environment variables
def validate_env_vars():
    required_vars = ['WYZE_EMAIL', 'WYZE_PASSWORD', 'WYZE_KEY_ID', 'WYZE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing_vars)}\n"
            "Please check your .env file and ensure all required variables are set."
        )

def get_wyze_info():
    try:
        # Login to Wyze
        response = Client().login(
            email=os.getenv('WYZE_EMAIL'),
            password=os.getenv('WYZE_PASSWORD'),
            key_id=os.getenv('WYZE_KEY_ID'),
            api_key=os.getenv('WYZE_API_KEY')
        )

        client = Client(token=response['access_token'])

        # Get device information
        devices_info = []
        for device in client.devices_list():
            device_info = {
                'mac': device.mac,
                'nickname': device.nickname,
                'is_online': device.is_online,
                'product_model': device.product.model
            }
            devices_info.append(device_info)

        return {
            'access_token': response['access_token'],
            'refresh_token': response['refresh_token'],
            'devices': devices_info
        }
    except WyzeApiError as e:
        return {'error': str(e)}

def get_client():
    """Helper function to get an authenticated Wyze client"""
    response = Client().login(
        email=os.getenv('WYZE_EMAIL'),
        password=os.getenv('WYZE_PASSWORD'),
        key_id=os.getenv('WYZE_KEY_ID'),
        api_key=os.getenv('WYZE_API_KEY')
    )
    return Client(token=response['access_token'])

@app.route("/toggle/<mac>/<action>")
def toggle_device(mac, action):
    try:
        client = get_client()
        device = next((d for d in client.devices_list() if d.mac == mac), None)
    #
    #     client.plugs.turn_off(device_mac=device.mac, device_model=device.product.model)
    #
    #     return f"<p>Turning {device.nickname} {action}</p>"
    #
    #
    # except WyzeApiError as e:
    #     return f"Error controlling device: {str(e)}"

        if device:
            if action == "on":
                client.plugs.turn_on(device_mac=device.mac, device_model=device.product.model)
            elif action == "off":
                client.plugs.turn_off(device_mac=device.mac, device_model=device.product.model)

        return redirect(url_for('hello_world'))
    except WyzeApiError as e:
        return f"Error controlling device: {str(e)}"


@app.route("/")
def hello_world():
    wyze_info = get_wyze_info()

    # Create HTML output
    if 'error' in wyze_info:
        return f"<p>Error: {wyze_info['error']}</p>"

    html = "<h1>Wyze Device Information</h1>"

    html += "<h2>Devices:</h2>"
    for device in wyze_info['devices']:
        html += "<div style='margin-bottom: 20px; padding: 10px; border: 1px solid #ccc;'>"
        html += f"<p><strong>Nickname:</strong> {device['nickname']}</p>"
        html += f"<p><strong>MAC:</strong> {device['mac']}</p>"
        html += f"<p><strong>Status:</strong> {'Online' if device['is_online'] else 'Offline'}</p>"
        html += f"<p><strong>Model:</strong> {device['product_model']}</p>"

        # Add control buttons
        if device['is_online']:
            html += f"""
                <p>
                    <a href="/toggle/{device['mac']}/on" style="padding: 5px 10px; background: #4CAF50; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px;">
                        Turn On
                    </a>
                    <a href="/toggle/{device['mac']}/off" style="padding: 5px 10px; background: #f44336; color: white; text-decoration: none; border-radius: 4px;">
                        Turn Off
                    </a>
                </p>
            """
        else:
            html += "<p><em>Device is offline - cannot control</em></p>"

        html += "</div>"

    return html
