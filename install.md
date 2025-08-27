# Wyze Flask App Setup on Raspberry Pi

Instructions for deploying to a Raspberry Pi, using nginx as a reverse proxy and systemd for service management.

## Step 1: Install Required System Packages

```bash
sudo apt update
sudo apt install python3-venv python3-pip nginx
```

## Step 2: Set Up Project Directory and Virtual Environment

```bash
cd ~
mkdir wyze
cd wyze

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install required Python packages
pip install flask gunicorn
# Add any other packages your app needs (requests, etc.)
```

## Step 3: Create Your Flask Application

Create your main Flask app file (`main.py`):

```python
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Wyze Camera Control App is running!"

# Add your camera control routes here

if __name__ == '__main__':
    app.run(debug=True)
```

## Step 4: Create Systemd Service File

Create the service file:

```bash
sudo nano /etc/systemd/system/wyze-flask.service
```

Add this content (**Important: Use `/tmp` for the socket location**):

```ini
[Unit]
Description=Gunicorn instance to serve Wyze Flask App
After=network.target

[Service]
User=bronson
Group=www-data
WorkingDirectory=/home/bronson/wyze
Environment="PATH=/home/bronson/wyze/.venv/bin"
ExecStart=/home/bronson/wyze/.venv/bin/gunicorn --workers 3 --bind unix:/tmp/wyze-flask.sock -m 007 main:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always

[Install]
WantedBy=multi-user.target
```

**Note:** Replace `bronson` with your actual username in the paths above.

## Step 5: Configure Nginx

Create nginx site configuration:

```bash
sudo nano /etc/nginx/sites-available/wyze-flask
```

Add this content:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        include proxy_params;
        proxy_pass http://unix:/tmp/wyze-flask.sock;
    }
}
```

Enable the site and disable the default:

```bash
sudo ln -s /etc/nginx/sites-available/wyze-flask /etc/nginx/sites-enabled
sudo unlink /etc/nginx/sites-enabled/default
```

## Step 6: Set Up Directory Permissions

**Critical Step:** Nginx needs access to your home directory to reach the socket file if you use a path in your home directory. However, using `/tmp` avoids this issue entirely.

If you ever need to use a socket in your home directory, you would need:

```bash
chmod 755 /home/your-username
chmod 755 /home/your-username/wyze
```

## Step 7: Start and Enable Services

```bash
# Test nginx configuration
sudo nginx -t

# Start and enable the Flask service
sudo systemctl start wyze-flask.service
sudo systemctl enable wyze-flask.service

# Restart nginx
sudo systemctl restart nginx
```

## Step 8: Verify Everything is Working

Check service status:

```bash
sudo systemctl status wyze-flask.service
```

Check nginx error logs if there are issues:

```bash
sudo tail -f /var/log/nginx/error.log
```

Test the socket directly:

```bash
curl --unix-socket /tmp/wyze-flask.sock http://localhost/
```

## Accessing Your App

Your Flask app will be accessible at:
- `http://your-pi-ip-address/`
- Example: `http://192.168.1.100/`

## Troubleshooting Common Issues

### 1. 502 Bad Gateway Error

**Most common cause:** Permission issues with socket file.

- **Solution:** Use `/tmp/` for socket location (as shown above)
- **Alternative:** If using home directory, ensure proper permissions:
  ```bash
  chmod 755 /home/your-username
  chmod 755 /home/your-username/wyze
  ```

### 2. Service Won't Start

Check the service logs:
```bash
sudo journalctl -u wyze-flask.service -f
```

Common issues:
- Wrong paths in service file
- Python environment issues
- Missing dependencies

### 3. Nginx Configuration Errors

Test nginx config:
```bash
sudo nginx -t
```

### 4. Can't Access from Network

- Check if Pi's firewall is blocking port 80
- Verify Pi's IP address: `ip addr show`

## Useful Commands

```bash
# Restart Flask service after code changes
sudo systemctl restart wyze-flask.service

# View Flask service logs
sudo journalctl -u wyze-flask.service -f

# View nginx error logs
sudo tail -f /var/log/nginx/error.log

# Check service status
sudo systemctl status wyze-flask.service
sudo systemctl status nginx
```

## Key Lessons Learned

1. **Socket Location Matters:** Using `/tmp/` for the Unix socket avoids complex permission issues with home directories.

2. **Permission Requirements:** If using home directory paths, nginx needs execute permissions on all parent directories.

3. **Service Dependencies:** The systemd service should specify `After=network.target` to ensure network is available.

4. **User/Group Configuration:** Flask service runs as your user but with `www-data` group for socket access.

5. **Testing is Important:** Always test nginx configuration with `sudo nginx -t` before restarting.

This setup will automatically start your Flask app on boot and restart it if it crashes, providing a reliable way to serve your Wyze camera controls over the network.

kotlin.Unit

