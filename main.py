from flask import Flask, redirect, url_for, request, flash
import os
import time
from wyze_sdk.errors import WyzeApiError, WyzeClientError
from dotenv import load_dotenv

# Load environment variables before anything reads them.
load_dotenv()

from logging_setup import setup_logging, log_files, read_log
import wyze_keepalive
# Import the single instance of our token manager from the refactored file
from token_manager import token_manager
from button_config import button_config

logger = setup_logging("web")
wyze_keepalive.enable()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')  # Add to your .env file

# WyzeClientError covers configuration failures such as a client that cannot
# refresh. It is NOT a subclass of WyzeApiError, so it has to be named
# explicitly or it escapes as a 500 - which is exactly how this app used to
# fail silently an hour after every restart.
WYZE_ERRORS = (WyzeApiError, WyzeClientError)


@app.before_request
def _log_request():
    request._started = time.monotonic()


@app.after_request
def _log_response(response):
    elapsed = (time.monotonic() - getattr(request, "_started", time.monotonic())) * 1000
    logger.info("%s %s -> %s (%.0fms)", request.method, request.path,
                response.status_code, elapsed)
    return response


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

        if not device:
            logger.warning("toggle requested for unknown mac %s", mac)
            return f"Device {mac} not found", 404
        logger.info("toggling %s (%s, type=%s) -> %s",
                    device.nickname, device.mac, device.type, action)

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
    except WYZE_ERRORS as e:
        logger.exception("failed to toggle %s: %s", mac, e)
        return f"Error controlling device: {str(e)}", 502


@app.route("/set_button_group", methods=["POST"])
def set_button_group():
    """Replace the button group with whatever was ticked in edit mode."""
    macs = request.form.getlist("macs")
    try:
        client = token_manager.get_client()
        by_mac = {d.mac: d for d in client.devices_list()}
    except WYZE_ERRORS as e:
        logger.exception("could not load devices while saving button group: %s", e)
        flash(f"❌ Error saving group: {e}", "error")
        return redirect(url_for('index'))

    # Store the live nickname so the group list stays readable, and ignore any
    # mac that is not actually in the account.
    selected = [{"mac": mac, "nickname": by_mac[mac].nickname}
                for mac in macs if mac in by_mac]

    if button_config.set_button_devices(selected):
        if selected:
            flash("✅ Button group saved: " +
                  ", ".join(d["nickname"] for d in selected), "success")
        else:
            flash("Button group is now empty", "info")
    else:
        flash("❌ Failed to save button group", "error")

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
    except WYZE_ERRORS as e:
        logger.exception("carriage page failed: %s", e)
        return f"Error controlling device: {str(e)}", 502


@app.route("/")
def index():
    try:
        # Validate environment variables on first load
        validate_env_vars()
        # Get the single, managed client instance
        client = token_manager.get_client()
        devices = client.devices_list()
    except (WyzeApiError, WyzeClientError, EnvironmentError) as e:
        logger.exception("index failed: %s", e)
        return f"<p>Error: {e}</p><p><a href='/logs'>View logs</a></p>", 502

    # Get current button configuration
    edit_mode = request.args.get("edit") == "1"
    group = button_config.get_button_devices()

    # Stored nicknames are snapshots taken when the group was saved. Renaming a
    # device in the Wyze app leaves them stale, so the group box and the device
    # list disagree and it looks like a member is missing. Matching is by MAC,
    # so only the label drifts - resync it here.
    if group:
        by_mac = {d.mac: d for d in devices}
        renamed = False
        for entry in group:
            live = by_mac.get(entry["mac"])
            if live is None:
                logger.warning("button group member %s (%s) is not in this account",
                               entry.get("nickname"), entry["mac"])
            elif live.nickname != entry.get("nickname"):
                logger.info("button group member renamed %r -> %r; updating "
                            "button_config.json", entry.get("nickname"), live.nickname)
                entry["nickname"] = live.nickname
                renamed = True
        if renamed:
            button_config.set_button_devices(group)
            group = button_config.get_button_devices()

    group_macs = {d["mac"] for d in group}

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
            .group-list { list-style: none; padding: 0; margin: 10px 0; }
            .group-list li { display: inline-block; background: #2196F3; color: white;
                             padding: 4px 10px; border-radius: 12px; margin: 3px;
                             font-size: 13px; font-weight: bold; }
            .device.selected { border-color: #2196F3; background: #f8f9ff; }
            .pick { display: flex; align-items: center; gap: 10px; }
            .pick input { width: 22px; height: 22px; }
            .editbar { position: sticky; bottom: 0; background: #fff; padding: 12px;
                       border-top: 2px solid #2196F3; text-align: center; margin-top: 10px; }
            .hint { color: #666; font-size: 13px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1> Wyze Device Controller</h1>
            <p><a href="/logs">View logs &amp; token status</a></p>
    """

    # Add flash messages
    html += """
            <div class="flash-messages">
                <!-- Flash messages would go here if using Flask's flash system -->
            </div>
    """

    # Show the button group, or the edit form header
    if edit_mode:
        html += """
            <div class="button-status">
                <h3>Edit Button Group</h3>
                <p class="hint">Tick every device the GPIO button should control,
                   then save. Pressing the button moves them all to the same state.</p>
            </div>
        """
        # The device list below lives inside this form so one Save submits it all.
        html += '<form method="POST" action="/set_button_group">'
    else:
        if group:
            members = "".join(f"<li>{d['nickname']}</li>" for d in group)
            html += f"""
            <div class="button-status">
                <h3>GPIO Button Group</h3>
                <ul class="group-list">{members}</ul>
                <p class="hint">Pressing the button reads all {len(group)} device(s)
                   and moves them to whichever state most are not in.</p>
                <a href="/?edit=1" class="btn btn-button">Edit button group</a>
            </div>
            """
        else:
            html += """
            <div class="button-status">
                <h3>GPIO Button Group</h3>
                <p><em>No devices configured for GPIO button control</em></p>
                <a href="/?edit=1" class="btn btn-button">Edit button group</a>
            </div>
            """

    html += "<h2> Available Devices</h2>"

    for device in devices:
        in_group = device.mac in group_macs
        device_class = "device selected" if in_group else "device"

        html += f'<div class="{device_class}">'

        if edit_mode:
            # A checkbox per device; the surrounding form posts them together.
            checked = " checked" if in_group else ""
            offline_note = "" if device.is_online else \
                ' <span class="device-status offline">Offline</span>'
            html += f"""
                <label class="pick">
                    <input type="checkbox" name="macs" value="{device.mac}"{checked}>
                    <span>
                        <span class="device-name">{device.nickname}</span>{offline_note}
                        <br><span class="hint">{device.type} &middot; {device.mac}</span>
                    </span>
                </label>
            """
            html += '</div>'
            continue

        html += '<div class="device-header">'
        html += f'<div class="device-name">{device.nickname}</div>'
        html += '<div>'

        if in_group:
            html += '<span class="button-controlled-badge">In Button Group</span> '

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
        else:
            html += "<p><em>Device is offline - cannot control</em></p>"

        html += '</div></div>'

    if edit_mode:
        html += """
            <div class="editbar">
                <button type="submit" class="btn btn-on">Save group</button>
                <a href="/" class="btn btn-secondary">Cancel</a>
            </div>
            </form>
        """

    html += """
        </div>
    </body>
    </html>
    """

    return html


@app.route("/logs")
@app.route("/logs/<name>")
def logs(name=None):
    """Read the application logs from the browser.

    Deliberately unauthenticated for now, matching the rest of the app; the
    logging filter redacts credentials so nothing sensitive is served here.
    """
    available = log_files()
    if not available:
        return "<p>No logs yet. They appear under logs/ once the app runs.</p>"
    if name is None or name not in available:
        name = available[0]

    try:
        lines = min(int(request.args.get("lines", 200)), 5000)
    except ValueError:
        lines = 200

    status = token_manager.status()
    body = read_log(name, lines)

    tabs = " ".join(
        f'<a class="tab{" active" if f == name else ""}" href="/logs/{f}?lines={lines}">{f}</a>'
        for f in available
    )
    rows = "".join(
        f"<tr><th>{k.replace('_', ' ')}</th><td>{'-' if v is None else v}</td></tr>"
        for k, v in status.items()
    )

    return f"""<!DOCTYPE html>
<html><head><title>Logs - Wyze Controller</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  .tab {{ display: inline-block; padding: 8px 14px; background: #fff; border: 1px solid #ddd;
         border-radius: 4px; text-decoration: none; color: #333; margin-right: 6px; }}
  .tab.active {{ background: #2196F3; color: #fff; border-color: #2196F3; }}
  table {{ border-collapse: collapse; margin: 16px 0; background: #fff; }}
  th, td {{ text-align: left; padding: 6px 12px; border: 1px solid #ddd; font-size: 14px; }}
  th {{ background: #f0f0f0; font-weight: bold; }}
  pre {{ background: #1e1e1e; color: #e6e6e6; padding: 14px; border-radius: 6px;
        overflow-x: auto; font-size: 12px; line-height: 1.45; max-height: 65vh; }}
  .muted {{ color: #666; font-size: 13px; }}
</style></head><body><div class="container">
<h1>Logs</h1>
<p><a href="/">&larr; Back to devices</a></p>
<h3>Token status</h3>
<table>{rows}</table>
<h3>Log files</h3>
<p>{tabs}</p>
<p class="muted">Showing the last {lines} lines of <strong>{name}</strong>.
   <a href="/logs/{name}?lines=1000">Show 1000</a> &middot;
   <a href="/logs/{name}?lines={lines}">Refresh</a></p>
<pre>{body.replace("&", "&amp;").replace("<", "&lt;")}</pre>
<p class="muted">On the Pi: <code>tail -f ~/wyze/logs/{name}</code>
   or <code>journalctl -u wyze-flask -f</code></p>
</div></body></html>"""


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
