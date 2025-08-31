import json
import os
import logging
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def load_settings() -> Dict[str, Any]:
    default_settings = {
        "SCAN_INTERVAL": int(os.getenv("DEFAULT_SCAN_INTERVAL", 3600)),
        "TOP_N_SIGNALS": int(os.getenv("DEFAULT_TOP_N_SIGNALS", 5)),
        "MAX_LOSS_PCT": -15.0,
        "TP_PERCENT": 0.15,
        "SL_PERCENT": 0.05,
        "LEVERAGE": float(os.getenv("LEVERAGE", 20)),
        "RISK_PCT": float(os.getenv("RISK_PCT", 0.01)),
        "VIRTUAL_BALANCE": 100.0,  # Matches capital.json
        "ENTRY_BUFFER_PCT": float(os.getenv("ENTRY_BUFFER_PCT", 0.002))
    }

    try:
        if not os.path.exists("settings.json"):
            logger.warning("settings.json not found, using default settings")
            return default_settings

        with open("settings.json", "r") as f:
            settings = json.load(f)

        for key, value in default_settings.items():
            if key not in settings:
                logger.warning(f"Missing {key} in settings.json, using default: {value}")
                settings[key] = value
            else:
                try:
                    if isinstance(value, (int, float)):
                        settings[key] = float(settings[key])
                        if key in ["LEVERAGE", "RISK_PCT", "VIRTUAL_BALANCE", "ENTRY_BUFFER_PCT"]:
                            if settings[key] <= 0:
                                logger.warning(f"Invalid {key} value {settings[key]}, using default: {value}")
                                settings[key] = value
                        if key == "MAX_LOSS_PCT" and settings[key] > 0:
                            logger.warning(f"Invalid MAX_LOSS_PCT value {settings[key]}, using default: {value}")
                            settings[key] = value
                    if key == "TOP_N_SIGNALS":
                        settings[key] = int(settings[key])
                        if settings[key] <= 0:
                            logger.warning(f"Invalid TOP_N_SIGNALS value {settings[key]}, using default: {value}")
                            settings[key] = value
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid {key} value {settings[key]} in settings.json, using default: {value}")
                    settings[key] = value

        logger.info("Successfully loaded settings from settings.json")
        return settings

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding settings.json: {e}, using default settings")
        return default_settings
    except Exception as e:
        logger.error(f"Error loading settings.json: {e}, using default settings")
        return default_settings