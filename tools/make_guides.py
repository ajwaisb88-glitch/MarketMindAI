"""Generate the MarketMind AI User Guide and Author (Owner) Guide as PDFs."""
import sys
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                HRFlowable, ListFlowable, ListItem, PageBreak)

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "."

GOLD = colors.HexColor("#B8860B")
INK = colors.HexColor("#1c2530")
DIM = colors.HexColor("#5b6675")
BG = colors.HexColor("#0d1117")
PANEL = colors.HexColor("#f4f1e8")
GREEN = colors.HexColor("#1a7f37")
RED = colors.HexColor("#b3261e")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=22,
                    textColor=INK, spaceAfter=2, leading=26)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5,
                     textColor=DIM, spaceAfter=14)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13.5,
                    textColor=GOLD, spaceBefore=16, spaceAfter=6, leading=16)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5,
                      textColor=INK, leading=15.5, spaceAfter=6, alignment=TA_LEFT)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=6, spaceAfter=3)
NOTE = ParagraphStyle("NOTE", parent=BODY, fontSize=9.5, textColor=DIM, leading=13)
CODE = ParagraphStyle("CODE", parent=ss["Code"], fontName="Courier", fontSize=9,
                      textColor=colors.HexColor("#0a3069"), backColor=PANEL,
                      borderPadding=6, leading=13, spaceAfter=8, spaceBefore=2)
WARN = ParagraphStyle("WARN", parent=BODY, fontName="Helvetica-Bold", fontSize=10, textColor=RED)


def hr():
    return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#d5cdb8"),
                      spaceBefore=4, spaceAfter=10)


def bullets(items, style=BULLET):
    return ListFlowable([ListItem(Paragraph(t, style), leftIndent=10, value="•") for t in items],
                        bulletType="bullet", start="•", leftIndent=12)


def brandbar(title, subtitle, tag):
    t = Table([[Paragraph(f'<font color="#B8860B">◆</font>  <b>{title}</b>', H1)],
               [Paragraph(subtitle, SUB)]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (0, 0), 0)]))
    return [t, Paragraph(f'<font color="#5b6675" size="8">{tag}</font>', NOTE), hr()]


def infobox(rows):
    data = [[Paragraph(f"<b>{k}</b>", NOTE), Paragraph(v, NOTE)] for k, v in rows]
    t = Table(data, colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5cdb8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5ddc8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d5cdb8"))
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(DIM)
    canvas.drawString(20 * mm, 10 * mm, "MarketMind AI")
    canvas.drawRightString(190 * mm, 10 * mm, f"Page {doc.page}")
    canvas.drawCentredString(105 * mm, 10 * mm, "MarketMind AI · by Malik Muhammad Naveed · +92 343 3333344 · +92 300 5009379")
    canvas.restoreState()


def build(path, story):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="MarketMind AI", author="MarketMind AI")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", path)


# ─────────────────────────── USER GUIDE ───────────────────────────
def user_guide():
    s = []
    s += brandbar("MarketMind AI — User Guide", "Institutional signals for gold, forex and crypto — in one app.",
                  "Getting started • connecting your broker • reading signals • trading modes")

    s.append(Paragraph("What this app does", H2))
    s.append(Paragraph(
        "MarketMind AI reads the market the way institutions do — order flow, volume, "
        "market structure and global money flow — and turns it into clear, graded signals with a "
        "concrete entry, stop and target. Three independent engines run side by side; you choose which "
        "ones you want and whether they trade automatically or just alert you.", BODY))

    s.append(Paragraph("First run — what you need", H2))
    s.append(infobox([
        ("Internet", "Required. Crypto (Binance) and money-flow data come from the web."),
        ("MetaTrader 5", "For gold / forex signals and auto-trading. Free from your broker."),
        ("Crypto", "Works with no account and no keys — data is public."),
        ("Your licence key", "Paste it in Settings on first launch (see your seller)."),
    ]))
    s.append(Spacer(1, 6))

    s.append(Paragraph("Connect MetaTrader 5 (for gold &amp; forex)", H2))
    s.append(bullets([
        "Install MT5 from your broker and log in (a <b>demo account is perfect</b> to start).",
        "In MT5, click the <b>AutoTrading</b> button in the toolbar so it turns green — required if you want auto-trade.",
        "Open MarketMind AI. It finds your broker's gold symbol automatically "
        "(XAUUSD, GOLD, XAUUSD.m … brokers name it differently).",
        "That's it — no API keys. The app talks to your local terminal directly.",
    ]))

    s.append(Paragraph("The three signal systems", H2))
    s.append(Paragraph("Each runs on its own and is never blended into one number:", BODY))
    s.append(infobox([
        ("Monster", "Full confluence score (0–100): higher-timeframe trend, Better Volume retest, "
                    "session, 60-Agents pressure and a quick trigger. Fires only at 68+ with 3 of 5 factors."),
        ("Whale", "Better Volume — reads climax, churn and absorption bars (smart-money footprints)."),
        ("MarketMind", "Crypto — a spoofing radar on the live order book, plus intraday and long-term reads."),
    ]))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Only A-tier signals (A+, A1, A) are shown as actionable — the weak ones are filtered out.", NOTE))

    s.append(Paragraph("Choosing how each system trades", H2))
    s.append(Paragraph("For every system you pick one mode:", BODY))
    s.append(bullets([
        "<b>Off</b> — ignore this system.",
        "<b>Manual</b> — the signal is shown only. A one-click pop-up appears with the entry, stop, "
        "target and a freshness countdown; you press <b>Trade</b> or skip it.",
        "<b>Auto</b> — the signal is sent straight to MT5 as an order (with stop and target).",
    ]))
    s.append(Paragraph("Mix freely: e.g. Monster on Auto, MarketMind on Manual, Whale Off.", NOTE))

    s.append(Paragraph("The Money Flow page", H2))
    s.append(Paragraph(
        "A separate read of where the world's money is moving today — a live tree from Fed net "
        "liquidity, through currencies, into asset classes and individual instruments, with a regime "
        "label, rotation, and plain-English <b>warnings</b> (for example: <i>flows are fighting a "
        "draining liquidity backdrop</i>). It never feeds the trade score — it's context you read yourself.", BODY))

    s.append(Paragraph("Trading safely", H2))
    s.append(Paragraph("Please read this before risking real money:", WARN))
    s.append(bullets([
        "<b>Start on a demo account.</b> Watch the signals fill and resolve before funding anything.",
        "Auto-trade places real orders on <b>your</b> account — set your lot size and keep it small.",
        "Signals are analysis, not advice. No system wins every trade; a stop can be hit.",
        "Nothing trades unless you enable Auto <i>and</i> AutoTrading is on in MT5.",
    ]))

    s.append(Paragraph("Entering your licence", H2))
    s.append(bullets([
        "Open Settings and paste the licence key your seller gave you.",
        "The app checks it offline — no account or sign-in needed.",
        "If your key is locked to one PC, the app shows your <b>Machine ID</b> in Settings; give that to your seller.",
        "When a key nears expiry the app tells you the days remaining.",
    ]))
    build(f"{OUT_DIR}/MarketMind-AI-User-Guide.pdf", s)


# ─────────────────────── AUTHOR / OWNER GUIDE ───────────────────────
def author_guide():
    s = []
    s += brandbar("MarketMind AI — Owner Guide", "For the product owner: licensing, data keys, security and rebuilds.",
                  "CONFIDENTIAL — not for customers")

    s.append(Paragraph("What ships vs. what stays with you", H2))
    s.append(infobox([
        ("Ships in the exe", "All 3 engines, money flow, MT5 + Binance connectors, execution, UI, "
                             "and the licence VERIFIER (public key only)."),
        ("Stays with YOU", "The licence GENERATOR (tools/license_gen.py) and your PRIVATE signing key. "
                           "Never distribute these."),
        ("Buyer supplies", "Their own MT5 terminal + broker login, internet, and (optional) their own free FRED key."),
    ]))

    s.append(Paragraph("Licensing — one-time setup", H2))
    s.append(Paragraph("Generate your signing keypair once. Keep the private key secret; put the public key in the app.", BODY))
    s.append(Paragraph("python tools/license_gen.py keygen", CODE))
    s.append(bullets([
        "Save the <b>PRIVATE KEY</b> somewhere safe (password manager). It signs every licence.",
        "Paste the <b>PUBLIC KEY</b> into <font face='Courier'>Backend/app/licensing.py</font> "
        "(<font face='Courier'>PUBLIC_KEY_HEX</font>) or set <font face='Courier'>MARKETMIND_LICENSE_PUBKEY</font>.",
        "In the product build set <font face='Courier'>MARKETMIND_REQUIRE_LICENSE=1</font> so a valid key is required.",
    ]))

    s.append(Paragraph("Issuing a licence per customer", H2))
    s.append(Paragraph("set MM_LICENSE_PRIVKEY=your_private_key_hex<br/>"
                       "python tools/license_gen.py issue --email malik@x.com --days 30 --tier pro", CODE))
    s.append(bullets([
        "<b>--days</b> sets the expiry. The date is signed in — the buyer cannot edit it.",
        "<b>--tier</b> is lite / pro / elite.",
        "<b>--machine &lt;id&gt;</b> (optional) locks the key to one PC. Ask the buyer for the Machine ID "
        "shown in the app's Settings (or GET /license).",
        "Send the printed key to the customer; they paste it into Settings.",
    ]))
    s.append(Paragraph("Because keys are Ed25519-signed, a forged or edited key (including a changed expiry) "
                       "fails verification instantly — proven in the test suite.", NOTE))

    s.append(Paragraph("Data sources & keys", H2))
    s.append(infobox([
        ("Binance", "Crypto + PAX Gold. Public, no key. Fallback to binance.us for restricted regions."),
        ("MetaTrader 5", "Broker gold / forex + tick volume + execution. The buyer's terminal, no key."),
        ("FRED", "Real Fed net liquidity for Money Flow. Needs a free key in FRED_API_KEY; "
                 "without it, liquidity falls back to a yield/dollar proxy. Recommend the buyer uses their own."),
        ("Yahoo / DefiLlama", "Stocks, bonds, metals, VIX and real stablecoin mint/burn. Public."),
    ]))

    s.append(Paragraph("Security — do before selling", H2))
    s.append(Paragraph("These are must-fix, not optional:", WARN))
    s.append(bullets([
        "Generate your OWN licence keypair (don't ship the placeholder public key).",
        "Never commit or embed the private signing key, or any FRED/OpenAI keys, in the exe.",
        "Rotate the plaintext API keys that were sitting in the old whale <font face='Courier'>config.json</font>.",
        "Set strong values for any admin password / secret before a production build.",
    ]))

    s.append(Paragraph("Rebuilding the app", H2))
    s.append(Paragraph("cd DesktopApp<br/>npm run build:win", CODE))
    s.append(Paragraph("This builds the UI, bundles the backend into one exe (polars, MetaTrader5, cryptography, "
                       "fredapi, sklearn all collected), and packages the Windows app into "
                       "<font face='Courier'>dist-build/</font> (installer + <font face='Courier'>win-unpacked/</font> folder).", BODY))

    s.append(Paragraph("Honest positioning (protects you)", H2))
    s.append(bullets([
        "Sell it as <b>signals + optional execution on the buyer's own account</b> — not a managed fund.",
        "Auto-execution on others' money can carry regulatory/liability exposure; check your jurisdiction.",
        "Publish honest, auto-graded results — never fabricated win-rates.",
        "No desktop app is 100% crack-proof; signed keys stop casual sharing and expiry-cheating, which is the realistic goal.",
    ]))
    build(f"{OUT_DIR}/MarketMind-AI-Owner-Guide.pdf", s)


def installation_guide():
    s = []
    s += brandbar("MarketMind AI — Installation Guide",
                  "Get up and running in a few minutes. Windows 10/11.",
                  "Install · Activate · Connect MetaTrader 5")

    s.append(Paragraph("What you need", H2))
    s.append(infobox([
        ("Windows PC", "Windows 10 or 11, 64-bit. ~1 GB free disk."),
        ("Internet", "Required — live crypto (Binance), money-flow and session data."),
        ("License key", "The key you were given by the seller. You activate it on first launch."),
        ("MetaTrader 5", "Needed for real gold/forex signals & auto-trading. Free from your broker."),
    ]))

    s.append(Paragraph("Step 1 — Install the app", H2))
    s.append(bullets([
        "Unzip the folder you received (right-click &rarr; Extract All).",
        "Open the <b>App</b> folder and double-click <b>MarketMind AI.exe</b>.",
        "If Windows shows &ldquo;unknown publisher&rdquo;, click <b>More info &rarr; Run anyway</b> "
        "(the app is unsigned — that is normal for a direct-sale build).",
        "First launch takes ~15–30 seconds while the engine starts.",
    ]))

    s.append(Paragraph("Step 2 — Activate your license key", H2))
    s.append(bullets([
        "On first launch you&rsquo;ll see the <b>Activate</b> screen.",
        "Paste the <b>license key</b> the seller gave you and click <b>Activate</b>.",
        "That&rsquo;s it — the key is saved on this PC, so you won&rsquo;t need to enter it again.",
        "If your key is <b>machine-locked</b>, send the seller the <b>machine ID</b> shown on that screen and "
        "they&rsquo;ll issue a key bound to your PC.",
    ]))
    s.append(Paragraph("Keys have an expiry date. When it lapses, the Activate screen returns — "
                       "paste a renewed key to continue.", NOTE))

    s.append(Paragraph("Step 3 — Connect MetaTrader 5 (for gold &amp; forex)", H2))
    s.append(Paragraph("The app runs without MT5 (crypto + a live gold proxy still work), but for real "
                       "XAUUSD prices and auto-trading you need MetaTrader 5:", BODY))
    s.append(bullets([
        "Install <b>MetaTrader 5</b> from your broker&rsquo;s website and log in. "
        "<b>Use a DEMO account to start</b> — prove the signals before risking real money.",
        "Keep the MT5 terminal <b>open</b> while you use MarketMind AI.",
        "To allow auto-trading, click the <b>AutoTrading</b> button in the MT5 toolbar so it turns green.",
        "Nothing trades automatically unless you set a system to <b>Auto</b> in the app <i>and</i> AutoTrading is on.",
    ]))

    s.append(Paragraph("Step 4 — First look", H2))
    s.append(bullets([
        "<b>Signals</b> — the three systems; A+ setups only.",
        "<b>Read</b> — the live market math for gold (order flow + order-book + volume × time) with a pinpoint entry.",
        "<b>Sessions</b> — the Dubai-time clock; watch London open and the New York overlap.",
        "<b>Performance</b> — the live scoreboard of how signals did (TP vs SL).",
    ]))

    s.append(Spacer(1, 6))
    s.append(Paragraph("Signals are analysis, not financial advice. Start on a demo account and trade your own "
                       "account at your own risk.", WARN))
    s.append(Paragraph("Support &amp; keys", H2))
    s.append(infobox([
        ("Author", "Malik Muhammad Naveed"),
        ("Contact", "+92 343 3333344 &nbsp; / &nbsp; +92 300 5009379"),
    ]))
    build(f"{OUT_DIR}/MarketMind-AI-Installation-Guide.pdf", s)


user_guide()
author_guide()
installation_guide()
