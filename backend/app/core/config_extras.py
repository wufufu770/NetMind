
from __future__ import annotations
from typing import Dict, Any
from .security import SECURITY

def get_security_config() -> Dict[str, Any]:
    return SECURITY.snapshot()

def update_security(payload: Dict[str, Any]) -> Dict[str, Any]:
    return SECURITY.configure(payload)

FONT_CONFIG = {
    'font_family': 'Inter, PingFang SC, Microsoft YaHei, sans-serif',
    'code_font_family': 'JetBrains Mono, SFMono-Regular, Consolas, monospace',
    'custom_font_url': '',
    'allow_upload': False,
}

def update_fonts(payload: Dict[str, Any]) -> Dict[str, Any]:
    FONT_CONFIG.update(payload)
    return FONT_CONFIG
