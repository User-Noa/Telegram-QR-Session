#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
💼 Telegram Business Funnel - Configuration Module
=============================================================================
Central configuration for multi-account sales funnel automation.
Supports HyperGap and extensible to other anonymous chat bots.
"""

import os
from typing import Dict, Any, Tuple, Optional

# Base Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

try:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Telegram API Credentials
# ---------------------------------------------------------------------------
API_ID: int = int(os.getenv("API_ID", "20579339"))
API_HASH: str = os.getenv("API_HASH", "46188ecc09a9b8d3f934d280b19c1f39")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "7658952456"))
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# SOCKS5 Proxy Configuration
# When deployed on Cloud (Render, Railway, HuggingFace, VPS outside Iran), PROXY is automatically None (direct).
# When running locally in Iran, PROXY defaults to local SOCKS5 ("socks5", "127.0.0.1", 10808).
IS_CLOUD: bool = bool(os.getenv("RENDER") or os.getenv("DOCKER_CONTAINER") or os.getenv("IS_CLOUD"))
DISABLE_PROXY: bool = os.getenv("DISABLE_PROXY", "false").lower() in ("true", "1", "yes") or IS_CLOUD

if DISABLE_PROXY:
    PROXY: Optional[Tuple[str, str, int]] = None
else:
    PROXY: Optional[Tuple[str, str, int]] = ("socks5", "127.0.0.1", 10808)

# ---------------------------------------------------------------------------
# Sales Funnel & Target Settings
# ---------------------------------------------------------------------------
# The destination username the bot directs leads to search in Telegram
TARGET_USERNAME: str = "mm98345"

# Safe representation without English letters to bypass HyperGap anti-spam
# e.g., "دو تا ام انگلیسی ۹۸۳۴۵"
TARGET_PHONETIC: str = "دو تا ام انگلیسی ۹۸۳۴۵"

# Maximum time (in seconds) to wait for partner response before auto-skipping
# Set to 75 seconds to give users ample time to search and send a DM
INACTIVITY_TIMEOUT: float = 75.0

# Debounce delay (in seconds) to aggregate rapid bursts of incoming messages
# Allows partner to finish typing multiple short lines before processing as one unified thought
DEBOUNCE_DELAY: float = 1.4

# LLM Brain Model (Groq LPU Qwen 3.8 27B)
GROQ_MODEL: str = "qwen/qwen3.8-27b"
NOA_SENSORY_PATH: str = "/home/MohammadHossein/Documents/Programing Languages/Python/Noa-Sensory"

# ---------------------------------------------------------------------------
# Anonymous Chat Bots Configurations
# ---------------------------------------------------------------------------
BOTS_CONFIG: Dict[str, Dict[str, Any]] = {
    "hypergap": {
        "name": "HyperGap",
        "username": "HyperGapBot",
        "entity": 6147663509,  # HyperGap bot entity ID
        "cmd_connect": "به یه ناشناس وصلم کن!",
        "cmd_get_profile": "👀 پروفایل مخاطب 👤",
        "cmd_end": "پایان چت",
        "has_purge": True,
        "shansi_button_data": b"shansi",
        "like_button_prefix": b"like_p",
    }
}

DEFAULT_BOT_KEY = "hypergap"
