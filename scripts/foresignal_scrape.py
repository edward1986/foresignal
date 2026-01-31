from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = "https://foresignal.com/en/"
TZ = ZoneInfo("Asia/Manila")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

LAST_STATE_FILE = DATA_DIR / "latest_signals.json"

MAP = "670429+-. 5,813"
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


# ---------- FETCH + DECODE ----------

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def decode_f(encoded: str) -> str:
    return "".join(
        MAP[ord(ch) - 65 - i]
        for i, ch in enumerate(encoded)
        if 0 <= ord(ch) - 65 - i < len(MAP)
    ).strip()


def extract_value(value_el) -> str:
    script = value_el.find("script")
    if script:
        m = re.search(r"f\('([^']+)'\)", script.text)
        if m:
            return decode_f(m.group(1))

    txt = value_el.get_text(" ", strip=True)
    txt = re.sub(r"f\('[^']+'\)", "", txt)
    m = NUM_RE.search(txt)
    return m.group(0) if m else ""


# ---------- PARSE ----------

def parse_signals(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    signals = []

    for card in soup.select(".card.signal-card"):
        pair = card.select_one(".card-header a").text.strip()
        status_el = card.select_one(".signal-row.signal-status")
        status = status_el.text.strip() if status_el else ""

        row = {
            "pair": pair,
            "status": status,
            "sell_at": "",
            "take_profit_at": "",
            "stop_loss_at": "",
            "buy_at": "",
            "bought_at": "",
            "sold_at": "",
        }

        for r in card.select(".signal-row"):
            title = r.select_one(".signal-title")
            value = r.select_one(".signal-value")
            if not title or not value:
                continue

            t = title.text.strip()
            v = extract_value(value)

            if t == "Sell at":
                row["sell_at"] = v
            elif t.startswith("Take profit"):
                row["take_profit_at"] = v
            elif t == "Stop loss at":
                row["stop_loss_at"] = v
            elif t == "Buy at":
                row["buy_at"] = v
            elif t == "Bought at":
                row["bought_at"] = v
            elif t == "Sold at":
                row["sold_at"] = v

        signals.append(row)

    # stable order
    return sorted(signals, key=lambda x: x["pair"])


# ---------- CHANGE DETECTION ----------

def has_changed(old: list[dict] | None, new: list[dict]) -> bool:
    if old is None:
        return True
    return old != new


# ---------- TELEGRAM HTML ----------

def build_html(signals: list[dict], timestamp: str) -> str:
    lines = [
        "<b>📊 Foresignal – Signal Update</b>",
        f"<i>🕒 {timestamp} (UTC+8)</i>",
        ""
    ]

    for s in signals:
        lines.append(f"<b>{s['pair']}</b>")
        lines.append(f"Status: <b>{s['status']}</b>")

        if s["sell_at"]:
            lines.append(f"Sell: <code>{s['sell_at']}</code>")
        if s["buy_at"]:
            lines.append(f"Buy:  <code>{s['buy_at']}</code>")
        if s["bought_at"]:
            lines.append(f"Buy:  <code>{s['bought_at']}</code>")
        if s["sold_at"]:
            lines.append(f"Sell: <code>{s['sold_at']}</code>")
        if s["take_profit_at"]:
            lines.append(f"TP:   <code>{s['take_profit_at']}</code>")
        if s["stop_loss_at"]:
            lines.append(f"SL:   <code>{s['stop_loss_at']}</code>")

        lines.append("")

    return "\n".join(lines)


def send_telegram(html: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    ).raise_for_status()


# ---------- MAIN ----------

def main():
    now = datetime.now(TZ)
    timestamp = now.strftime("%Y-%m-%d %H:%M")

    html = fetch_html(URL)
    current = parse_signals(html)

    previous = None
    if LAST_STATE_FILE.exists():
        previous = json.loads(LAST_STATE_FILE.read_text())

    if not has_changed(previous, current):
        print("No change detected — Telegram not sent.")
        return

    # Save latest state
    LAST_STATE_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")

    # Send Telegram
    message = build_html(current, timestamp)
    send_telegram(message)

    print("Change detected — Telegram sent.")


if __name__ == "__main__":
    main()
