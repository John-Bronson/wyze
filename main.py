from flask import Flask, redirect, url_for
import os
from wyze_sdk.errors import WyzeApiError
from dotenv import load_dotenv

# Import the single instance of our token manager from the refactored file
from token_manager import token_manager

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Validate required environment variables at startup
def validate_env_vars():
    required_vars = ['WYZE_EMAIL', 'WYZE_PASSWORD', 'WYZE_KEY_ID', 'WYZE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing_vars)}\n"
            "Please check your .env file and ensure all required variables are set."
        )

# We no longer need get_wyze_info() or the old get_client()

@app.route("/toggle/<mac>/<action>")
def toggle_device(mac, action):
    try:
        # Get the single, managed client instance
        client = token_manager.get_client()
        device = next((device for device in client.devices_list() if device.mac == mac), None)

        device_controllers = {
            'MeshLight': client.bulbs,
            'Plug': client.plugs
        }

        controller = device_controllers.get(device.type)

        if device:
            if action == "on":
                controller.turn_on(device_mac=device.mac, device_model=device.product.model)
            elif action == "off":
                controller.turn_off(device_mac=device.mac, device_model=device.product.model)

        return redirect(url_for('index'))
    except WyzeApiError as e:
        return f"Error controlling device: {str(e)}"

@app.route("/carriage/")
def carriage():
    try:
        # Get the single, managed client instance
        client = token_manager.get_client()
        device = next((d for d in client.devices_list() if d.mac == "2CAA8E5460E2"), None) # floor lamp
        if not device:
            return "<p>Carriage device not found.</p>"

        html = f"""
            <p>
                <a href="/toggle/{device.mac}/on" style="font-size: 74px; padding: 20px 10px; padding-top: 200px; background: #4CAF50; color: white; text-decoration: none; border-radius: 4px; margin-bottom: 10px;">
                    Turn On
                </a>
                <br />
                <a href="/toggle/{device.mac}/off" style="font-size: 74px; padding: 5px 10px; background: #f44336; color: white; text-decoration: none; border-radius: 4px;">
                    Turn Off
                </a>
            </p>
        """
        return html
    except WyzeApiError as e:
        return f"Error controlling device: {str(e)}"

@app.route("/")
def index():
    try:
        # Validate environment variables on first load
        validate_env_vars()
        # Get the single, managed client instance
        client = token_manager.get_client()
        devices = client.devices_list()
    except (WyzeApiError, EnvironmentError) as e:
        return f"<p>Error: {e}</p>"

    # Create HTML output
    html = "<h1>Wyze Device Information</h1>"
    html += "<h2>Devices:</h2>"
    for device in devices:
        html += "<div style='margin-bottom: 20px; padding: 10px; border: 1px solid #ccc;'>"
        html += f"<p><strong>Nickname:</strong> {device.nickname}</p>"
        html += f"<p><strong>MAC:</strong> {device.mac}</p>"
        html += f"<p><strong>Status:</strong> {'Online' if device.is_online else 'Offline'}</p>"
        html += f"<p><strong>Model:</strong> {device.product.model}</p>"

        if device.is_online:
            html += f"""
                <p>
                    <a href="/toggle/{device.mac}/on" style="padding: 5px 10px; background: #4CAF50; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px;">
                        Turn On
                    </a>
                    <a href="/toggle/{device.mac}/off" style="padding: 5px 10px; background: #f44336; color: white; text-decoration: none; border-radius: 4px;">
                        Turn Off
                    </a>
                </p>
            """
        else:
            html += "<p><em>Device is offline - cannot control</em></p>"
        html += "</div>"
    return html

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)