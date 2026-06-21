#!/bin/bash
set -e

# --- CONFIGURATION ---
SERVICE_NAME="vnet_ledger"
FOLDER="Loans"
APP_PORT="8888"
GITHUB_REPO="VihanNethmira/vnetledgersystem"
GITHUB_API="https://api.github.com/repos/$GITHUB_REPO/releases"
WORK_DIR="/root/$FOLDER"

# ─────────────────────────────────────────────
#   HELPER FUNCTIONS
# ─────────────────────────────────────────────

print_header() {
    clear
    echo "================================================"
    echo "   VNET SHOP - UNIVERSAL DEPLOYMENT TOOL"
    echo "   Repo : github.com/$GITHUB_REPO"
    echo "   OS   : Ubuntu  |  App Port: $APP_PORT (internal)"
    echo "================================================"
}

select_release() {
    echo ""
    echo "Fetching available releases from GitHub..."

    RELEASE_JSON=$(curl -s "$GITHUB_API")

    mapfile -t TAGS < <(echo "$RELEASE_JSON" | grep -o '"tag_name": *"[^"]*"' | sed 's/"tag_name": *"//;s/"//')
    mapfile -t ZIPS < <(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*VNET_Ledger\.zip"' | sed 's/"browser_download_url": *"//;s/"//')

    if [ ${#TAGS[@]} -eq 0 ]; then
        echo "ERROR: No releases found for $GITHUB_REPO."
        exit 1
    fi

    echo ""
    echo "Available releases:"
    for i in "${!TAGS[@]}"; do
        if [ -n "${ZIPS[$i]}" ]; then
            echo "  $((i+1)). ${TAGS[$i]}  [VNET_Ledger.zip ready]"
        else
            echo "  $((i+1)). ${TAGS[$i]}  (no asset)"
        fi
    done
    echo ""
    read -p "Select release [1-${#TAGS[@]}]: " REL_NUM

    if ! [[ "$REL_NUM" =~ ^[0-9]+$ ]] || [ "$REL_NUM" -lt 1 ] || [ "$REL_NUM" -gt ${#TAGS[@]} ]; then
        echo "ERROR: Invalid selection."
        exit 1
    fi

    SELECTED_TAG="${TAGS[$((REL_NUM-1))]}"
    SELECTED_ZIP="${ZIPS[$((REL_NUM-1))]}"

    if [ -z "$SELECTED_ZIP" ]; then
        echo "ERROR: Release '${SELECTED_TAG}' has no VNET_Ledger.zip asset."
        exit 1
    fi

    echo ""
    echo "  → Release : $SELECTED_TAG"
    echo "  → Asset   : $SELECTED_ZIP"
    echo ""
}

# ─────────────────────────────────────────────
#   MAIN MENU
# ─────────────────────────────────────────────

print_header
echo "1. Full Install (Download Release)"
echo "2. Update (Switch / Re-deploy Release)"
echo "3. Uninstall / Remove System"
echo "4. Check Service Status"
echo "5. Exit"
echo ""
read -p "Choose an option (1-5): " MAIN_OPT

# ─────────────────────────────────────────────
#   1 & 2 — INSTALL / UPDATE
# ─────────────────────────────────────────────

if [ "$MAIN_OPT" == "1" ] || [ "$MAIN_OPT" == "2" ]; then

    read -p "Enter Domain (e.g., yourdomain.com): " DOMAIN
    read -p "Enter Nginx Port (e.g., 9000): " PORT

    select_release

    # ── Dependencies ──────────────────────────────
    echo "[1/6] Installing system dependencies..."
    sudo apt-get update -qq
    sudo apt-get install -y python3-pip python3-venv nginx certbot python3-certbot-nginx curl unzip rsync

    # ── Download Release Asset ─────────────────────
    ZIP_PATH="/tmp/${SERVICE_NAME}_release.zip"
    EXTRACT_TMP="/tmp/${SERVICE_NAME}_extract"

    echo "[2/6] Downloading VNET_Ledger.zip ($SELECTED_TAG)..."
    curl -fsSL -L -o "$ZIP_PATH" "$SELECTED_ZIP"

    echo "[3/6] Extracting..."
    rm -rf "$EXTRACT_TMP"
    mkdir -p "$EXTRACT_TMP"
    unzip -q "$ZIP_PATH" -d "$EXTRACT_TMP"

    # ── Detect structure: flat or wrapped in subfolder ──
    APP_FILE=$(find "$EXTRACT_TMP" -name "app.py" | head -n 1)
    if [ -z "$APP_FILE" ]; then
        echo "ERROR: app.py not found inside VNET_Ledger.zip"
        exit 1
    fi
    APP_SOURCE_DIR=$(dirname "$APP_FILE")
    echo "  → app.py found at: $APP_FILE"

    # ── Stop service before touching files ────────
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true

    # ── Deploy: sync app files, preserve existing venv & database ──
    mkdir -p "$WORK_DIR"
    rsync -a --delete \
        --exclude='venv/' \
        --exclude='*.db' \
        --exclude='*.sqlite' \
        --exclude='*.sqlite3' \
        "$APP_SOURCE_DIR/" "$WORK_DIR/"

    echo "  → Files deployed to $WORK_DIR"
    rm -rf "$ZIP_PATH" "$EXTRACT_TMP"

    # ── Python Virtual Environment ─────────────────
    echo "[4/6] Setting up Python environment..."
    python3 -m venv "$WORK_DIR/venv"
    source "$WORK_DIR/venv/bin/activate"

    if [ -f "$WORK_DIR/requirements.txt" ]; then
        echo "  → Installing from requirements.txt..."
        pip install -q -r "$WORK_DIR/requirements.txt"
    else
        echo "  → No requirements.txt found, installing flask + gunicorn..."
        pip install -q flask gunicorn
    fi

    # Always ensure gunicorn is installed
    pip install -q gunicorn

    # Verify app.py loads correctly before writing service
    echo "  → Verifying app.py loads..."
    cd "$WORK_DIR"
    python3 -c "import app" && echo "  → app.py OK" || { echo "ERROR: app.py failed to import. Check dependencies."; exit 1; }

    # ── Systemd Service ────────────────────────────
    echo "[5/6] Configuring systemd service..."
    cat <<EOF | sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null
[Unit]
Description=Gunicorn - VNET Ledger $SELECTED_TAG
After=network.target

[Service]
User=root
WorkingDirectory=$WORK_DIR
ExecStart=$WORK_DIR/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:$APP_PORT app:app
Restart=always
RestartSec=5
Environment="RELEASE=$SELECTED_TAG"

[Install]
WantedBy=multi-user.target
EOF

    # ── SSL ────────────────────────────────────────
    echo "[6/6] Configuring SSL & Nginx..."
    sudo systemctl stop nginx 2>/dev/null || true

    # Skip certbot if cert already exists for this domain
    if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        sudo certbot certonly --standalone \
            -d "$DOMAIN" \
            --non-interactive \
            --agree-tos \
            --register-unsafely-without-email
    else
        echo "  → SSL cert already exists for $DOMAIN, skipping certbot."
    fi

    # ── Nginx Config ───────────────────────────────
    cat <<EOF | sudo tee /etc/nginx/sites-available/${SERVICE_NAME} > /dev/null
server {
    listen $PORT ssl;
    server_name $DOMAIN;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:$APP_PORT;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120;
        proxy_intercept_errors off;
    }
}
EOF

    sudo ln -sf /etc/nginx/sites-available/"$SERVICE_NAME" /etc/nginx/sites-enabled/"$SERVICE_NAME"
    sudo rm -f /etc/nginx/sites-enabled/default

    # Validate nginx config before starting
    sudo nginx -t

    # ── Start Everything ───────────────────────────
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    sudo systemctl start nginx

    # ── Firewall ───────────────────────────────────
    sudo ufw allow "$PORT"/tcp 2>/dev/null || true
    sudo ufw reload 2>/dev/null || true

    # ── Final health check ─────────────────────────
    sleep 3
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        echo ""
        echo "================================================"
        echo "  SUCCESS: Ledger $SELECTED_TAG is live!"
        echo "  URL    : https://$DOMAIN:$PORT"
        echo "================================================"
    else
        echo ""
        echo "================================================"
        echo "  WARNING: Service may not have started correctly."
        echo "  Run: sudo journalctl -u $SERVICE_NAME -n 30"
        echo "================================================"
    fi

# ─────────────────────────────────────────────
#   3 — UNINSTALL
# ─────────────────────────────────────────────

elif [ "$MAIN_OPT" == "3" ]; then
    read -p "Enter the Nginx Port to close: " UN_PORT

    echo "Removing VNET Ledger..."
    sudo systemctl stop "$SERVICE_NAME"    2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f /etc/systemd/system/"$SERVICE_NAME".service
    sudo systemctl daemon-reload

    sudo rm -f /etc/nginx/sites-enabled/"$SERVICE_NAME"
    sudo rm -f /etc/nginx/sites-available/"$SERVICE_NAME"
    sudo nginx -t && sudo systemctl restart nginx

    sudo ufw delete allow "$UN_PORT"/tcp 2>/dev/null || true
    sudo ufw reload 2>/dev/null || true

    read -p "Delete app files in /root/$FOLDER? (y/n): " DEL_FOLD
    if [ "$DEL_FOLD" == "y" ]; then
        sudo rm -rf "$WORK_DIR"
        echo "Folder deleted."
    fi
    echo "Uninstall complete."

# ─────────────────────────────────────────────
#   4 — STATUS
# ─────────────────────────────────────────────

elif [ "$MAIN_OPT" == "4" ]; then
    echo ""
    echo "── App Service ─────────────────────────────────"
    sudo systemctl status "$SERVICE_NAME" --no-pager || true
    echo ""
    echo "── Recent App Logs ─────────────────────────────"
    sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
    echo ""
    echo "── Nginx ───────────────────────────────────────"
    sudo systemctl status nginx --no-pager || true
    echo ""
    echo "── Firewall ────────────────────────────────────"
    sudo ufw status | grep ALLOW || echo "(UFW not active or no rules)"
    echo "────────────────────────────────────────────────"

else
    echo "Exiting."
    exit 0
fi
