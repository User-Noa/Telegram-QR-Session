# ⚡ Telegram Web QR Session Engine

High-performance, pure in-memory Telegram QR code authorization service built with **FastAPI**, **Telethon**, and **Docker**.

Stream authorized SQLite `.session` files and `StringSession` credentials directly to your Telegram Bot without writing a single byte to disk.

---

## 🌟 Key Features

- **Zero Disk Footprint:** 100% ephemeral in-memory authentication (`MemorySession`). Neither the client nor the server stores temporary session files on disk.
- **Direct Bot Delivery:** Serializes memory session directly into standard SQLite `.session` database bytes in RAM and streams them to the admin via Telegram Bot API with instant notifications.
- **StringSession Generation:** Emits full Telethon `StringSession` strings with native one-tap clipboard copy inside syntax-highlighted code headers.
- **Continuous QR Auto-Refresh:** Automatically recreates expiring QR tokens every 30 seconds seamlessly without breaking connections or requiring manual reloads.
- **2FA Ready:** Handles Two-Factor Authentication (cloud password) gracefully directly from the web interface.
- **Account Identity Naming:** Generated `.session` files are named dynamically after the account (e.g. `Username.session` or `Firstname_Lastname.session`).
- **Cloud & Production Ready:** Built with a production-ready non-root `Dockerfile` optimized for **Render**, **Railway**, **Hugging Face Spaces**, and VPS.

---

## 🏗️ Architecture & Workflow

```text
1. User visits Web UI (FastAPI)
   └─> Requests new QR session (/api/session/start)

2. Telethon initiates MemorySession with Telegram DC
   └─> Generates tg://login?token=... QR code data URL

3. User scans QR code with Telegram Mobile App
   ├─> If 2FA enabled: Prompts for password via UI (/api/session/2fa)
   └─> Upon authorization: In-memory session authenticated

4. RAM Serialization & Delivery
   ├─> Serializes MemorySession -> SQLite .session binary bytes in RAM
   ├─> Extracts Telethon StringSession
   └─> Streams .session file & credentials via Bot API to Admin

5. Cleanup
   └─> Disconnects client and purges RAM state (Zero disk usage)
```

---

## ⚙️ Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `API_ID` | Telegram API ID | Required |
| `API_HASH` | Telegram API Hash | Required |
| `BOT_TOKEN` | Telegram Bot Token for delivery | Required |
| `ADMIN_ID` | Telegram User ID of the recipient admin | Required |
| `PORT` | Web server port | `8000` |
| `DISABLE_PROXY`| Disable SOCKS5 proxy on cloud | `true` (on cloud) |

---

## 🚀 Deployment

### Deploy on Render
1. Push this repository to your GitHub.
2. In [Render Dashboard](https://dashboard.render.com), create a new **Web Service**.
3. Connect your GitHub repository.
4. Render automatically detects `Dockerfile` and `render.yaml`.
5. Set your environment variables in the Render dashboard and deploy!

### Run with Docker Locally
```bash
docker build -t telegram-qr-session .
docker run -p 8000:8000 telegram-qr-session
```

### Run with Python Directly
```bash
pip install -r requirements.txt
python web_qr/server.py
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 📡 API Endpoints

- `GET /` — Responsive dark-mode single-page QR authentication interface
- `GET /health` — Service health check & keep-alive monitor
- `POST /api/session/start` — Initializes in-memory Telethon client & generates QR code
- `POST /api/session/refresh` — Manually regenerates fresh QR code token
- `POST /api/session/2fa` — Submits two-factor cloud password
- `GET /api/session/status` — Returns current authentication state & countdown timer
- `POST /api/session/cancel` — Cancels active session and frees memory resources

---

## 🔒 Security & Privacy

- **No persistent storage:** Sessions are converted to bytes in memory, sent directly via encrypted Telegram Bot API, and discarded.
- **Non-root container:** The Docker container runs as UID `1000` (`user`).
- **Private delivery:** Sessions are sent exclusively to the configured `ADMIN_ID`.
