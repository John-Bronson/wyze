from flask import Flask, redirect, url_for, request, flash
import os
from wyze_sdk.errors import WyzeApiError
from dotenv import load_dotenv

# Import the single instance of our token manager from the refactored file
from token_manager import token_manager
from button_config import button_config

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')  # Add to your .env file

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


@app.route("/toggle/<mac>/<action>")
def toggle_device(mac, action):
    try:
        # Get the single, managed client instance
        client = token_manager.get_client()
        device = next((device for device in client.devices_list() if device.mac == mac), None)

        print(f"Toggling device: {device.nickname} ({device.mac}) of type {device.type} with action: {action}")
        print(device)

        device_controllers = {
            'Plug': client.plugs,
            'MeshLight': client.bulbs,
            'Bulb': client.bulbs,
            'Light': client.bulbs
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


@app.route("/set_button_device/<mac>")
def set_button_device(mac):
    """Set which device the GPIO button should control"""
    try:
        client = token_manager.get_client()
        device = next((device for device in client.devices_list() if device.mac == mac), None)

        if device:
            success = button_config.set_button_device(device.mac, device.nickname)
            if success:
                flash(f"✅ Button configured to control: {device.nickname}", "success")
            else:
                flash("❌ Failed to save button configuration", "error")
        else:
            flash("❌ Device not found", "error")

    except WyzeApiError as e:
        flash(f"❌ Error: {str(e)}", "error")

    return redirect(url_for('index'))


@app.route("/clear_button_device")
def clear_button_device():
    """Clear the button device configuration"""
    success = button_config.clear_button_device()
    if success:
        flash(" Button configuration cleared", "info")
    else:
        flash("❌ Failed to clear button configuration", "error")

    return redirect(url_for('index'))


@app.route("/carriage/")
def carriage():
    try:
        # Get the single, managed client instance
        client = token_manager.get_client()
        device = next((d for d in client.devices_list() if d.mac == "2CAA8E5460E2"), None)  # floor lamp
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

    # Get current button configuration
    current_button_device = button_config.get_button_device()

    # Create HTML output with enhanced styling
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Wyze Device Controller</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; }
            .button-status { 
                background: #e8f4f8; 
                border: 2px solid #2196F3; 
                border-radius: 8px; 
                padding: 15px; 
                margin-bottom: 20px;
                text-align: center;
            }
            .device { 
                background: white;
                margin-bottom: 20px; 
                padding: 15px; 
                border: 1px solid #ddd;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .device.button-controlled { 
                border-color: #2196F3;
                background: #f8f9ff;
            }
            .device-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .device-name { font-size: 18px; font-weight: bold; }
            .device-status { 
                padding: 4px 8px; 
                border-radius: 4px; 
                font-size: 12px; 
                font-weight: bold;
            }
            .online { background: #4CAF50; color: white; }
            .offline { background: #f44336; color: white; }
            .button-controlled-badge {
                background: #2196F3;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            .controls { margin-top: 10px; }
            .btn { 
                padding: 8px 16px; 
                text-decoration: none; 
                border-radius: 4px; 
                margin-right: 10px;
                font-weight: bold;
                display: inline-block;
                margin-bottom: 5px;
            }
            .btn-on { background: #4CAF50; color: white; }
            .btn-off { background: #f44336; color: white; }
            .btn-button { background: #2196F3; color: white; }
            .btn-secondary { background: #6c757d; color: white; }
            .btn:hover { opacity: 0.8; }
            .flash-messages { margin-bottom: 20px; }
            .flash { 
                padding: 10px; 
                border-radius: 4px; 
                margin-bottom: 10px;
            }
            .flash.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .flash.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            .flash.info { background: #d1ecf1; color: #0c5460; border: 1px solid #b8daff; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1> Wyze Device Controller</h1>
    """

    # Add flash messages
    html += """
            <div class="flash-messages">
                <!-- Flash messages would go here if using Flask's flash system -->
            </div>
    """

    # Show current button configuration
    if current_button_device:
        html += f"""
            <div class="button-status">
                <h3> GPIO Button Configuration</h3>
                <p><strong>Currently controlling:</strong> {current_button_device['nickname']}</p>
                <p><strong>MAC Address:</strong> {current_button_device['mac']}</p>
                <a href="/clear_button_device" class="btn btn-secondary">Clear Button Config</a>
            </div>
        """
    else:
        html += """
            <div class="button-status">
                <h3> GPIO Button Configuration</h3>
                <p><em>No device configured for GPIO button control</em></p>
                <p>Click "Set as Button Device" on any device below to configure it.</p>
            </div>
        """

    html += "<h2> Available Devices</h2>"

    for device in devices:
        is_button_device = (current_button_device and
                            current_button_device['mac'] == device.mac)

        device_class = "device button-controlled" if is_button_device else "device"

        html += f'<div class="{device_class}">'
        html += '<div class="device-header">'
        html += f'<div class="device-name">{device.nickname}</div>'
        html += '<div>'

        if is_button_device:
            html += '<span class="button-controlled-badge"> Button Device</span> '

        status_class = "online" if device.is_online else "offline"
        status_text = "Online" if device.is_online else "Offline"
        html += f'<span class="device-status {status_class}">{status_text}</span>'
        html += '</div></div>'

        html += f"<p><strong>Type:</strong> {device.type}</p>"
        html += f"<p><strong>MAC:</strong> {device.mac}</p>"
        html += f"<p><strong>Model:</strong> {device.product.model}</p>"

        html += '<div class="controls">'
        if device.is_online:
            html += f"""
                <a href="/toggle/{device.mac}/on" class="btn btn-on">Turn On</a>
                <a href="/toggle/{device.mac}/off" class="btn btn-off">Turn Off</a>
            """
            if not is_button_device:
                html += f"""
                    <a href="/set_button_device/{device.mac}" class="btn btn-button"> Set as Button Device</a>
                """
        else:
            html += "<p><em>Device is offline - cannot control</em></p>"

        html += '</div></div>'

    html += """
        </div>
    </body>
    </html>
    """

    return html


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
