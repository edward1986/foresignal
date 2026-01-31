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

MAP = "670429+-. 5,813"
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


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
    out = []
    for i, ch in enumerate(encoded):
        idx = ord(ch) - 65 - i
        if 0 <= idx < len(MAP):
            out.append(MAP[idx])
    return "".join(out).strip()


def extract_encoded(script: str) -> str | None:
    m = re.search(r"f\('([^']+)'\)", script or "")
    return m.group(1) if m else None


def extract_value(value_el) -> str:
    script = value_el.find("script")
    if script:
        enc = extract_encoded(script.text)
        if enc:
            return decode_f(enc)

    txt = value_el.get_text(" ", strip=True)
    txt = re.sub(r"f\('[^']+'\)", "", txt)
    m = NUM_RE.search(txt)
    return m.group(0) if m else ""


def parse_signals(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    rows = []

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

        rows.append(row)

    return pd.DataFrame(rows)


# -------- BEAUTIFUL TELEGRAM HTML --------

def build_html_message(df: pd.DataFrame, pulled_at: str) -> str:
    lines = [
        "<b>📊 Foresignal – Daily Signals</b>",
        f"<i>🕒 {pulled_at} (UTC+8)</i>",
        ""
    ]

    for _, r in df.iterrows():
        lines.append(f"<b>{r['pair']}</b>")
        lines.append(f"Status: <b>{r['status']}</b>")

        if r["sell_at"]:
            lines.append(f"Sell: <code>{r['sell_at']}</code>")
        if r["buy_at"]:
            lines.append(f"Buy:  <code>{r['buy_at']}</code>")
        if r["bought_at"]:
            lines.append(f"Buy:  <code>{r['bought_at']}</code>")
        if r["sold_at"]:
            lines.append(f"Sell: <code>{r['sold_at']}</code>")
        if r["take_profit_at"]:
            lines.append(f"TP:   <code>{r['take_profit_at']}</code>")
        if r["stop_loss_at"]:
            lines.append(f"SL:   <code>{r['stop_loss_at']}</code>")

        lines.append("")

    return "\n".join(lines)


def send_telegram_html(html: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram secrets not set")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    requests.post(url, json=payload, timeout=30).raise_for_status()


def main():
    now = datetime.now(TZ)
    pulled_at = now.strftime("%Y-%m-%d %H:%M")

    html = fetch_html(URL)
    df = parse_signals(html)

    Path("data").mkdir(exist_ok=True)

    # Save JSON
    json_payload = {
        "source": "foresignal.com",
        "pulled_at": pulled_at,
        "signals": df.to_dict(orient="records"),
    }
    Path(f"data/foresignal_{now.date()}.json").write_text(
        json.dumps(json_payload, indent=2), encoding="utf-8"
    )

    # Send beautiful HTML to Telegram
    message = build_html_message(df, pulled_at)
    send_telegram_html(message)

    print(message)


if __name__ == "__main__":
    main()
