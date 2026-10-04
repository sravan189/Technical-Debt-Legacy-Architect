import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html import escape

import streamlit as st
from google import genai
from google.genai import types


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Technical Debt & Legacy Architect",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONSTANTS
# ============================================================

MODELS = {
    "Gemini 2.5 Flash (fast, balanced)": "gemini-2.5-flash",
    "Gemini 2.5 Pro (deepest reasoning)": "gemini-2.5-pro",
    "Gemini 2.5 Flash-Lite (fastest)": "gemini-2.5-flash-lite",
}
# Tried in order if the selected model fails before producing any output.
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

# name -> (rgb of main accent, main accent, rgb of second accent, second accent)
ACCENTS = {
    "Blueprint": ("94,176,255", "#5eb0ff", "139,123,255", "#8b7bff"),
    "Emerald": ("74,222,155", "#4ade9b", "54,224,208", "#36e0d0"),
    "Sunset": ("255,181,71", "#ffb547", "255,122,89", "#ff7a59"),
    "Orchid": ("192,132,252", "#c084fc", "244,114,182", "#f472b6"),
}

MODES = {
    "Auto Detect": "",
    "Code Review": (
        "FOCUS: Treat the material as a code review. Prioritize bugs, code "
        "smells, SOLID violations, complexity, naming, error handling and "
        "give concrete refactored code."
    ),
    "Architecture": (
        "FOCUS: Treat the material as a system-design review. Prioritize "
        "components, coupling, data flow, bottlenecks, single points of "
        "failure, scalability and reliability."
    ),
    "Security Audit": (
        "FOCUS: Treat the material as a security audit. Prioritize injection, "
        "authentication, authorization, secrets, input validation, unsafe "
        "dependencies and map findings to OWASP categories where possible."
    ),
    "Database & API": (
        "FOCUS: Prioritize schema design, normalization, indexing, integrity, "
        "query risks, endpoint design, HTTP semantics, versioning and "
        "backward compatibility."
    ),
    "Debug & Logs": (
        "FOCUS: Treat the material as a debugging task. Explain the error, "
        "separate confirmed facts from inference, list root causes, "
        "debugging steps, an immediate fix and a long-term fix."
    ),
    "Modernization": (
        "FOCUS: Prioritize an incremental modernization strategy: strangler "
        "patterns, seams, test harnesses, phased migration and risk control."
    ),
}

DEPTHS = {
    "Concise": "DEPTH: Keep answers short. Top findings only, no long preambles.",
    "Balanced": "DEPTH: Be concise but technically useful.",
    "Deep dive": (
        "DEPTH: Be thorough. Cover every relevant dimension, justify "
        "trade-offs, and include improved code or diagrams (ASCII in code "
        "blocks) where they help."
    ),
}

ROLES = {
    "Student": (
        "AUDIENCE: A software engineering student. Explain advanced concepts "
        "clearly, define jargon the first time you use it and give small "
        "analogies."
    ),
    "Junior developer": (
        "AUDIENCE: A junior developer. Explain the why behind each "
        "recommendation and link it to common best practices."
    ),
    "Senior engineer": (
        "AUDIENCE: A senior engineer. Be dense and direct. Skip basics and "
        "focus on trade-offs."
    ),
    "Architect / Tech lead": (
        "AUDIENCE: An architect or tech lead. Focus on strategic risk, "
        "business impact, sequencing and cost of delay."
    ),
}

SYSTEM_PROMPT = """
You are Technical Debt & Legacy Architect: a senior software architect,
legacy-modernization specialist, code reviewer and technical-debt analyst.
You turn complexity into clear, actionable architectural insight.

You can analyze: source code in any mainstream language, code screenshots,
architecture / C4 / UML / sequence / data-flow diagrams, SQL schemas and ER
diagrams, API designs (OpenAPI, REST, GraphQL), errors, stack traces and logs,
Docker / Kubernetes / CI-CD / cloud configuration, and technical documents.

FIRST determine the material type, for example:
"Material type: Source Code — Java". If you cannot determine it confidently,
say so instead of inventing it.

ANALYSIS RULES
- Code: purpose, control flow, bugs, smells, duplication, complexity,
  coupling, cohesion, SOLID violations, security, performance, scalability.
  Provide improved code when useful.
- Architecture: components, communication paths, dependencies, bottlenecks,
  single points of failure, security boundaries, legacy patterns.
- Database: entities, keys, constraints, normalization, indexing, integrity.
- API: resource naming, HTTP semantics, validation, authN/authZ, errors,
  versioning, backward compatibility.
- Errors/logs: explain the error, likely root causes, separate confirmed facts
  from inference, debugging steps, immediate fix, long-term fix.

TECHNICAL DEBT PRIORITIES
P0 Critical, P1 High, P2 Medium, P3 Low. For each important item give:
Problem, Why it matters, Risk, Recommended fix, Priority.

MODERNIZATION
Phase 1 Stabilize, Phase 2 Refactor, Phase 3 Decouple, Phase 4 Modernize,
Phase 5 Optimize. Never recommend a full rewrite without explaining why.
Prefer incremental modernization.

RESPONSE STYLE
Use only the relevant sections from:
### 🔎 Material Detected
### 🧠 What It Does
### 🔴 Critical Risks
### 🟠 Technical Debt
### 🟡 Maintainability
### 🔐 Security
### ⚡ Performance
### 🟢 Recommended Fixes
### 🚀 Modernization Roadmap

Tag claims as FACT, INFERENCE or UNCERTAINTY where the difference matters.
Never invent information that cannot be seen or reasonably inferred.
For follow-up questions, answer directly without repeating the full structure.
End substantial analyses with a short "💡 Next steps" list of 2 or 3 actions.
"""

SUMMARY_PROMPT = """
Create a concise professional report from the entire conversation.

# Technical Debt & Legacy Architect Report
## Material Analyzed
## Executive Summary
## Critical Findings
## Technical Debt (P0 Critical, P1 High, P2 Medium, P3 Low)
## Security (only if relevant)
## Performance & Scalability (only if relevant)
## Recommended Fixes
## Modernization Roadmap (incremental)

Do not invent information. Use only the conversation and supplied material.
Keep it compact enough to read comfortably in Telegram.
"""

SCORECARD_PROMPT = """
Evaluate the material discussed in this conversation and return ONLY a JSON
object (no markdown fences, no commentary) with exactly this shape:

{
  "overall_score": <integer 0-100, higher is healthier>,
  "grade": "<A|B|C|D|F>",
  "verdict": "<one sentence summary>",
  "dimensions": [
    {"name": "Maintainability", "score": <0-100 or null>, "note": "<short>"},
    {"name": "Security", "score": <0-100 or null>, "note": "<short>"},
    {"name": "Performance", "score": <0-100 or null>, "note": "<short>"},
    {"name": "Scalability", "score": <0-100 or null>, "note": "<short>"},
    {"name": "Testability", "score": <0-100 or null>, "note": "<short>"},
    {"name": "Architecture", "score": <0-100 or null>, "note": "<short>"}
  ],
  "top_risks": ["<risk>", "<risk>", "<risk>"],
  "debt_items": [
    {"title": "<short finding, max 10 words>", "priority": "<P0|P1|P2|P3>", "effort": "<S|M|L>"}
  ],
  "quick_wins": ["<fix doable in under an hour>", "<fix>", "<fix>"]
}

Rules:
- Use null for any dimension that cannot be judged from the material.
- debt_items: 3 to 8 concrete findings, most urgent first.
- effort is S (under a day), M (a few days) or L (a week or more).
- Base everything only on what was actually supplied.
"""

# ---------- demo material ----------

DEMO_CODE = '''import sqlite3

DB_PASSWORD = "admin123"

def process(d, t, f=None):
    conn = sqlite3.connect("shop.db")
    c = conn.cursor()
    if t == "order":
        q = "SELECT * FROM orders WHERE user='" + d["user"] + "'"
        rows = c.execute(q).fetchall()
        total = 0
        for r in rows:
            total = total + r[3] * r[4]
            if r[5] == "EU":
                total = total * 1.21
            elif r[5] == "US":
                total = total * 1.07
            elif r[5] == "UK":
                total = total * 1.20
        print("Total:", total)
        if f:
            open(f, "w").write(str(total))
        return total
    elif t == "refund":
        c.execute("UPDATE orders SET status='refunded' WHERE id=" + str(d["id"]))
        conn.commit()
        print("refunded")
    # TODO: handle other types
'''

DEMO_SQL = """CREATE TABLE customers (
  id INT,
  name VARCHAR(255),
  email VARCHAR(255),
  address TEXT,
  orders TEXT,          -- comma separated order ids
  card_number VARCHAR(32)
);

CREATE TABLE orders (
  id INT,
  customer_name VARCHAR(255),
  total FLOAT,
  status VARCHAR(20),
  created VARCHAR(30)
);

SELECT * FROM orders WHERE customer_name LIKE '%smith%' ORDER BY created;
"""

DEMO_DOCKER = """FROM ubuntu:latest
RUN apt-get update && apt-get install -y python3 python3-pip curl vim git
COPY . /app
WORKDIR /app
RUN pip3 install -r requirements.txt
ENV DB_PASSWORD=admin123
EXPOSE 22 5000
USER root
CMD python3 app.py
"""

DEMO_LOG = """Exception in thread "http-nio-8080-exec-14" java.lang.NullPointerException
    at com.shop.billing.InvoiceService.calculateTax(InvoiceService.java:142)
    at com.shop.billing.InvoiceService.createInvoice(InvoiceService.java:88)
    at com.shop.web.OrderController.checkout(OrderController.java:61)
Caused by: java.sql.SQLTransientConnectionException: HikariPool-1 -
    Connection is not available, request timed out after 30000ms.
    at com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)
2024-03-02 02:14:09 WARN  Pool stats: total=10 active=10 idle=0 waiting=57
"""

DEMOS = [
    {
        "key": "py",
        "icon": "🐍",
        "title": "Legacy Python module",
        "desc": "SQL injection, hard-coded secrets and tangled branching.",
        "prompt": (
            "Here is a legacy Python module from an online shop. Give me a full "
            "technical-debt review with priorities and a refactored version.\n\n"
            f"```python\n{DEMO_CODE}```"
        ),
    },
    {
        "key": "sql",
        "icon": "🗄️",
        "title": "Weak database schema",
        "desc": "Missing keys, comma-separated lists and risky card storage.",
        "prompt": (
            "Review this SQL schema and query for design, integrity, indexing "
            "and security problems. Propose a better schema.\n\n"
            f"```sql\n{DEMO_SQL}```"
        ),
    },
    {
        "key": "docker",
        "icon": "🐳",
        "title": "Risky Dockerfile",
        "desc": "Root user, unpinned image and secrets in the image.",
        "prompt": (
            "Audit this Dockerfile for security, size, reproducibility and "
            "build-cache problems. Give a hardened version.\n\n"
            f"```dockerfile\n{DEMO_DOCKER}```"
        ),
    },
    {
        "key": "log",
        "icon": "🚨",
        "title": "Production stack trace",
        "desc": "A connection-pool timeout hiding behind a null pointer.",
        "prompt": (
            "Explain this production error. Separate confirmed facts from "
            "inference, list root causes, an immediate fix and a long-term fix."
            f"\n\n```\n{DEMO_LOG}```"
        ),
    },
]

FOLLOW_UPS = [
    ("🔍 Find tech debt",
     "Analyze everything supplied specifically for technical debt. Prioritize "
     "the findings P0 to P3."),
    ("🔐 Security audit",
     "Audit the supplied material for security issues. Map them to OWASP "
     "categories where possible and give fixes."),
    ("🛠️ Refactor it",
     "Rewrite the supplied code with the highest-priority problems fixed. "
     "Show the improved code and briefly explain each change."),
    ("🧪 Write tests",
     "Write a practical test suite for the supplied code, including edge "
     "cases and the bugs you found."),
    ("🚀 Roadmap",
     "Create an incremental modernization roadmap for this system with "
     "phases, priorities and risks."),
    ("🧒 Explain simply",
     "Explain what this material does and why its problems matter, in plain "
     "language for a beginner."),
]

TEXT_EXT = {
    "py", "java", "c", "cpp", "h", "hpp", "cs", "js", "jsx", "ts", "tsx",
    "go", "rs", "php", "kt", "swift", "rb", "sql", "sh", "bash", "yaml",
    "yml", "json", "xml", "toml", "ini", "cfg", "conf", "env", "md", "txt",
    "log", "csv",
}
IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
ALLOWED_TYPES = sorted((TEXT_EXT - {"bash", "env"}) | IMAGE_EXT | {"pdf"})
MAX_TEXT_CHARS = 200_000
MAX_UPLOAD_BYTES = 18 * 1024 * 1024

LABELS = {
    "py": "Python", "java": "Java", "cs": "C#", "js": "JavaScript",
    "ts": "TypeScript", "tsx": "TypeScript", "jsx": "JavaScript",
    "go": "Go", "rs": "Rust", "sql": "SQL", "yaml": "YAML", "yml": "YAML",
    "json": "JSON", "md": "Markdown", "log": "Log", "pdf": "PDF",
    "png": "Image", "jpg": "Image", "jpeg": "Image", "webp": "Image",
}

PRIORITY_META = {
    "P0": ("Critical", "#ff6b6b"),
    "P1": ("High", "#ffb547"),
    "P2": ("Medium", "#5eb0ff"),
    "P3": ("Low", "#4ade9b"),
}


# ============================================================
# SECRETS & CLIENT
# ============================================================

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    TELEGRAM_BOT_TOKEN = st.secrets["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID = str(st.secrets["TELEGRAM_CHAT_ID"])
except KeyError as error:
    st.error(f"Missing secret: {error}. Check .streamlit/secrets.toml.")
    st.stop()


@st.cache_resource
def get_client():
    return genai.Client(api_key=GEMINI_API_KEY)


client = get_client()


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "onboarded": False,
    "name": "",
    "role": "Student",
    "messages": [],      # what the UI shows
    "history": [],       # what Gemini sees (types.Content)
    "report": None,
    "scorecard": None,
    "summary_sent": False,
    "pending": None,
    "last_turn": None,   # inputs of the latest turn, for Regenerate
    "tokens": 0,
    "mode": "Auto Detect",
    "depth": "Balanced",
    "model_label": list(MODELS)[0],
    "temperature": 0.4,
    "accent": "Blueprint",
    "auto_score": False,
    "tg_attach": False,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


def reset_session():
    for key in ("messages", "history"):
        st.session_state[key] = []
    st.session_state.report = None
    st.session_state.scorecard = None
    st.session_state.summary_sent = False
    st.session_state.pending = None
    st.session_state.last_turn = None
    st.session_state.tokens = 0


# ============================================================
# STYLE  (blueprint palette: deep navy, drafting-line blue, amber for debt)
# ============================================================

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
    --bg: #060d18;
    --panel: rgba(15, 29, 48, 0.72);
    --panel-solid: #0e1c30;
    --panel-2: #132640;
    --line: #21395a;
    --line-soft: #172c47;
    --ink: #eaf2fc;
    --muted: #8197b3;
    --rgb: 94,176,255;
    --rgb2: 139,123,255;
    --blue: #5eb0ff;
    --violet: #8b7bff;
    --cyan: #36e0d0;
    --amber: #ffb547;
    --green: #4ade9b;
    --red: #ff6b6b;
    --grad: linear-gradient(135deg, var(--blue) 0%, var(--violet) 100%);
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    font-family: 'Manrope', system-ui, sans-serif;
}
::selection { background: rgba(var(--rgb),0.35); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #1f3555; border-radius: 10px; }
::-webkit-scrollbar-track { background: transparent; }
:focus-visible { outline: 2px solid var(--blue) !important; outline-offset: 2px; }

/* ---------- ambient background ---------- */
.stApp {
    background:
        radial-gradient(700px 480px at 6% -6%, rgba(var(--rgb),0.18), transparent 62%),
        radial-gradient(640px 460px at 98% 4%, rgba(var(--rgb2),0.14), transparent 60%),
        linear-gradient(rgba(var(--rgb),0.03) 1px, transparent 1px) 0 0 / 36px 36px,
        linear-gradient(90deg, rgba(var(--rgb),0.03) 1px, transparent 1px) 0 0 / 36px 36px,
        var(--bg);
    background-attachment: fixed;
    color: var(--ink);
}

#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1120px; padding-top: 1.1rem; padding-bottom: 7rem; }
code, pre, .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace !important; }

/* ---------- top bar ---------- */
.topbar {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 12px 16px; margin-bottom: 20px; border-radius: 18px;
    background: var(--panel); border: 1px solid var(--line-soft);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}
.brand { display: flex; align-items: center; gap: 13px; min-width: 0; }
.brand-icon {
    width: 44px; height: 44px; flex: none; border-radius: 13px; display: grid; place-items: center;
    font-size: 21px; background: var(--grad); box-shadow: 0 8px 24px rgba(var(--rgb),0.35);
}
.brand-name { font-size: 16px; font-weight: 800; letter-spacing: -0.3px; color: var(--ink); }
.brand-caption { font-size: 12px; color: var(--muted); margin-top: 2px; }
.status {
    display: inline-flex; align-items: center; gap: 8px; padding: 7px 13px; border-radius: 999px;
    font-size: 12px; font-weight: 700; color: var(--green); white-space: nowrap;
    background: rgba(74,222,155,0.09); border: 1px solid rgba(74,222,155,0.3);
}
.status i {
    width: 8px; height: 8px; border-radius: 50%; background: var(--green);
    box-shadow: 0 0 0 0 rgba(74,222,155,0.6); animation: pulse 2.2s infinite;
}
.status small { color: var(--muted); font-weight: 600; font-size: 11.5px; }
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(74,222,155,0.55); }
    70% { box-shadow: 0 0 0 9px rgba(74,222,155,0); }
    100% { box-shadow: 0 0 0 0 rgba(74,222,155,0); }
}

/* ---------- hero ---------- */
.hero {
    position: relative; display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 28px;
    align-items: center; padding: 46px 44px; border-radius: 26px; overflow: hidden;
    border: 1px solid transparent;
    background:
        linear-gradient(160deg, #0f2139, #091527) padding-box,
        linear-gradient(135deg, rgba(var(--rgb),0.7), rgba(var(--rgb2),0.25) 45%, rgba(54,224,208,0.5)) border-box;
    box-shadow: 0 40px 100px rgba(0,0,0,0.45), 0 0 80px rgba(var(--rgb),0.07);
    animation: rise .7s ease both;
}
@keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
.hero::before {
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background:
        linear-gradient(rgba(var(--rgb),0.07) 1px, transparent 1px) 0 0 / 22px 22px,
        linear-gradient(90deg, rgba(var(--rgb),0.07) 1px, transparent 1px) 0 0 / 22px 22px;
    -webkit-mask-image: linear-gradient(115deg, transparent 30%, #000 100%);
    mask-image: linear-gradient(115deg, transparent 30%, #000 100%);
}
.hero > * { position: relative; }
.hero h1 { margin: 0; font-size: 44px; line-height: 1.07; letter-spacing: -1.7px; font-weight: 800; color: var(--ink); }
.hero p { margin: 16px 0 0; max-width: 560px; color: var(--muted); font-size: 15px; line-height: 1.72; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 24px; }
.tag {
    padding: 7px 13px; border-radius: 999px; font-size: 12px; font-weight: 600; color: #bcdcff;
    background: rgba(var(--rgb),0.09); border: 1px solid rgba(var(--rgb),0.24);
}
.hero-art { display: grid; place-items: center; }
.hero-art svg { width: 100%; max-width: 380px; height: auto; filter: drop-shadow(0 18px 40px rgba(var(--rgb),0.22)); }
.flow { stroke-dasharray: 5 6; animation: dash 1.6s linear infinite; }
@keyframes dash { to { stroke-dashoffset: -22; } }

.stats-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0 4px; }
.stat-big { padding: 16px 18px; border-radius: 16px; background: var(--panel); border: 1px solid var(--line-soft); }
.stat-big b { display: block; font-size: 24px; font-weight: 800; letter-spacing: -0.8px; color: var(--ink); }
.stat-big span { font-size: 12px; color: var(--muted); }

/* ---------- feature cells ---------- */
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 14px 0 6px; }
.cell {
    position: relative; padding: 20px 18px; border-radius: 18px; overflow: hidden;
    background: var(--panel); border: 1px solid var(--line-soft);
}
.cell .ico {
    width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; font-size: 20px;
    background: rgba(var(--rgb),0.1); border: 1px solid rgba(var(--rgb),0.2);
}
.cell b { display: block; font-size: 14px; color: var(--ink); margin: 13px 0 5px; }
.cell span { font-size: 12.5px; color: var(--muted); line-height: 1.6; }

.panel-title { font-size: 19px; font-weight: 800; letter-spacing: -0.4px; color: var(--ink); margin: 26px 0 2px; }
.panel-sub { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.section-label { margin: 26px 0 8px; font-size: 13px; font-weight: 700; color: var(--muted); }

/* ---------- welcome ---------- */
.welcome {
    position: relative; padding: 34px 34px 30px; border-radius: 22px; overflow: hidden;
    border: 1px solid transparent;
    background:
        linear-gradient(160deg, #10233c, #0a1829) padding-box,
        linear-gradient(135deg, rgba(var(--rgb),0.55), rgba(var(--rgb2),0.2), rgba(54,224,208,0.4)) border-box;
    animation: rise .6s ease both;
}
.welcome::after {
    content: ""; position: absolute; right: -90px; top: -110px; width: 300px; height: 300px;
    border-radius: 50%; background: rgba(var(--rgb2),0.16); filter: blur(60px); pointer-events: none;
}
.welcome h2 { margin: 0; font-size: 30px; letter-spacing: -1px; font-weight: 800; color: var(--ink); }
.welcome p { margin: 11px 0 0; max-width: 680px; color: var(--muted); font-size: 14.5px; line-height: 1.72; }
.welcome .dropzone {
    margin-top: 18px; display: inline-flex; align-items: center; gap: 10px; padding: 11px 16px;
    border-radius: 12px; font-size: 13px; color: #bcdcff;
    border: 1.5px dashed rgba(var(--rgb),0.45); background: rgba(var(--rgb),0.06);
}

/* demo cards */
[class*="st-key-demo_"] {
    padding: 16px 16px 12px; border-radius: 18px; background: var(--panel);
    border: 1px solid var(--line-soft); transition: border-color .2s ease;
}
[class*="st-key-demo_"]:hover { border-color: rgba(var(--rgb),0.5); }
.demo-ico { font-size: 22px; }
.demo-title { font-size: 14px; font-weight: 800; color: var(--ink); margin: 8px 0 4px; }
.demo-desc { font-size: 12.5px; color: var(--muted); line-height: 1.55; min-height: 40px; }

.file-chip {
    display: inline-flex; align-items: center; gap: 8px; padding: 7px 12px; margin: 2px 6px 6px 0;
    border-radius: 10px; background: var(--panel-2); border: 1px solid var(--line);
    color: var(--ink); font-size: 12px;
}
.file-chip em { font-style: normal; color: var(--blue); font-weight: 700; }

/* ---------- chat ---------- */
[data-testid="stChatMessage"] {
    position: relative; background: var(--panel); border: 1px solid var(--line-soft);
    border-radius: 18px; padding: 18px 20px; margin-bottom: 14px; backdrop-filter: blur(10px);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"])::before {
    content: ""; position: absolute; left: 0; top: 16px; bottom: 16px; width: 3px;
    border-radius: 3px; background: var(--grad);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: linear-gradient(135deg, rgba(var(--rgb),0.14), rgba(var(--rgb2),0.10));
    border-color: rgba(var(--rgb),0.28);
}
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { font-size: 14.8px; line-height: 1.75; }
[data-testid="stChatMessage"] h3 {
    margin-top: 1.3rem; padding-bottom: 8px; font-size: 17.5px; font-weight: 800; letter-spacing: -0.3px;
    border-bottom: 1px solid var(--line-soft);
}
[data-testid="stChatMessage"] pre { border: 1px solid var(--line); border-radius: 14px; background: #050b14 !important; }
[data-testid="stChatMessage"] :not(pre) > code {
    background: rgba(var(--rgb),0.12); color: #bcdcff; padding: 2px 6px; border-radius: 6px;
}
[data-testid="stChatMessage"] table { border-radius: 12px; overflow: hidden; }

[data-testid="stChatInput"] {
    border-radius: 18px; border: 1px solid var(--line); background: var(--panel-solid);
    box-shadow: 0 14px 44px rgba(0,0,0,0.45);
}
[data-testid="stChatInput"]:focus-within {
    border-color: var(--blue); box-shadow: 0 0 0 4px rgba(var(--rgb),0.16), 0 14px 44px rgba(0,0,0,0.45);
}

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button,
[data-testid="stPopover"] > button {
    border-radius: 12px; border: 1px solid var(--line); background: var(--panel-2);
    color: var(--ink); font-weight: 700; font-size: 13px; padding: 0.5rem 0.9rem;
    transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stPopover"] > button:hover {
    border-color: var(--blue); background: #17304f; color: #fff; box-shadow: 0 8px 22px rgba(0,0,0,0.3);
}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: var(--grad); border: none; color: #061225; box-shadow: 0 8px 26px rgba(var(--rgb),0.32);
}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
    background: var(--grad); color: #061225; filter: brightness(1.1); box-shadow: 0 12px 34px rgba(var(--rgb),0.5);
}
.stButton > button:disabled { opacity: 0.4; box-shadow: none; }

/* message action row: quieter than the main buttons */
[class*="st-key-actions"] .stButton > button, [class*="st-key-actions"] [data-testid="stPopover"] > button {
    background: transparent; border-color: var(--line-soft); color: var(--muted); font-size: 12.5px; padding: 0.3rem 0.7rem;
}
[class*="st-key-actions"] .stButton > button:hover, [class*="st-key-actions"] [data-testid="stPopover"] > button:hover {
    color: var(--ink); background: var(--panel-2);
}

/* inputs */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div {
    background: var(--panel-solid) !important; border-radius: 12px !important; border-color: var(--line) !important;
}
[data-testid="stExpander"] { border: 1px solid var(--line-soft); border-radius: 16px; background: var(--panel); }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0a1628, #070f1c); border-right: 1px solid var(--line-soft); }
[data-testid="stSidebar"] .side-h { margin: 22px 0 8px; font-size: 12.5px; font-weight: 800; color: var(--blue); }
.side-card {
    display: flex; align-items: center; gap: 12px; padding: 14px; border-radius: 16px;
    background: var(--panel); border: 1px solid var(--line-soft);
}
.avatar {
    width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center;
    font-weight: 800; font-size: 16px; color: #061225; background: var(--grad);
    box-shadow: 0 6px 18px rgba(var(--rgb),0.35);
}
.side-user { font-size: 15px; font-weight: 800; color: var(--ink); }
.side-role { font-size: 12px; color: var(--muted); margin-top: 2px; }
.detected {
    margin-top: 10px; padding: 9px 12px; border-radius: 12px; font-size: 12.5px; color: #bcdcff;
    background: rgba(var(--rgb),0.08); border: 1px solid rgba(var(--rgb),0.22); line-height: 1.45;
}
.stat-row { display: flex; gap: 10px; margin-top: 8px; }
.stat { flex: 1; padding: 12px; border-radius: 13px; background: var(--panel); border: 1px solid var(--line-soft); }
.stat b { display: block; font-size: 19px; font-weight: 800; color: var(--ink); }
.stat span { font-size: 11px; color: var(--muted); }

/* ---------- scorecard ---------- */
.score-wrap {
    display: flex; gap: 24px; align-items: center; padding: 20px; margin-bottom: 10px;
    border-radius: 18px; background: var(--panel-solid); border: 1px solid var(--line);
}
.score-ring {
    --p: 50; width: 120px; height: 120px; flex: none; border-radius: 50%; display: grid; place-items: center;
    background: conic-gradient(var(--c) calc(var(--p) * 1%), #17294a 0);
    box-shadow: 0 0 34px color-mix(in srgb, var(--c) 28%, transparent);
}
.score-inner {
    width: 94px; height: 94px; border-radius: 50%; background: var(--panel-solid);
    display: grid; place-content: center; text-align: center;
}
.score-inner span { font-size: 34px; font-weight: 800; color: var(--c); line-height: 1; }
.score-inner small { font-size: 11px; color: var(--muted); margin-top: 4px; }
.score-verdict { font-size: 15.5px; line-height: 1.65; color: var(--ink); }
.risk {
    padding: 10px 14px; margin-top: 8px; border-radius: 12px; font-size: 13px; color: #ffd699;
    background: rgba(255,181,71,0.07); border: 1px solid rgba(255,181,71,0.26);
}
.win {
    padding: 10px 14px; margin-top: 8px; border-radius: 12px; font-size: 13px; color: #b9f5d8;
    background: rgba(74,222,155,0.07); border: 1px solid rgba(74,222,155,0.24);
}
[data-testid="stProgress"] > div > div > div > div { background: var(--grad); }

.radar { display: grid; place-items: center; padding: 6px 0; }
.radar svg { width: 100%; max-width: 330px; height: auto; }
.radar .rg { fill: none; stroke: var(--line); stroke-width: 1; }
.radar .ra { stroke: var(--line-soft); stroke-width: 1; }
.radar .rv { fill: rgba(var(--rgb),0.22); stroke: var(--blue); stroke-width: 2; }
.radar .rd { fill: var(--blue); }
.radar text { fill: var(--muted); font-size: 11px; font-weight: 700; font-family: 'Manrope', sans-serif; }

/* ---------- priority board: the memorable element ---------- */
.board { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 8px; }
.bcol { border-radius: 16px; background: var(--panel-solid); border: 1px solid var(--line-soft); overflow: hidden; }
.bhead {
    display: flex; align-items: center; justify-content: space-between; padding: 11px 14px;
    border-top: 3px solid var(--pc); border-bottom: 1px solid var(--line-soft);
}
.bhead b { font-size: 13px; color: var(--ink); }
.bhead b em { font-style: normal; color: var(--pc); margin-right: 6px; }
.bhead span { font-size: 12px; font-weight: 800; color: var(--pc); }
.bbody { padding: 10px; display: grid; gap: 8px; min-height: 64px; }
.ditem {
    padding: 10px 11px; border-radius: 11px; font-size: 12.5px; line-height: 1.5; color: var(--ink);
    background: var(--panel-2); border: 1px solid var(--line-soft); border-left: 3px solid var(--pc);
}
.ditem i {
    display: inline-block; margin-top: 6px; padding: 1px 8px; border-radius: 999px; font-style: normal;
    font-size: 11px; font-weight: 700; color: var(--muted); border: 1px solid var(--line);
}
.bempty { font-size: 12px; color: #5d728d; padding: 6px 4px; }

.telegram-ok {
    padding: 11px 13px; border-radius: 12px; font-size: 12px; line-height: 1.5; margin-top: 8px;
    background: rgba(74,222,155,0.08); border: 1px solid rgba(74,222,155,0.28); color: var(--green);
}
.footer { margin-top: 30px; text-align: center; color: #50657f; font-size: 11.5px; }

@media (max-width: 900px) {
    .hero { grid-template-columns: 1fr; padding: 30px 22px; }
    .hero-art { display: none; }
    .hero h1 { font-size: 32px; }
    .grid4, .stats-strip, .board { grid-template-columns: repeat(2, 1fr); }
    .score-wrap { flex-direction: column; align-items: flex-start; }
    .brand-caption { display: none; }
}
@media (max-width: 520px) { .grid4, .stats-strip, .board { grid-template-columns: 1fr; } .status small { display: none; } }
@media (prefers-reduced-motion: reduce) { *, *::before { animation: none !important; transition: none !important; } }
"""


def accent_css(name):
    rgb, blue, rgb2, violet = ACCENTS.get(name, ACCENTS["Blueprint"])
    return (
        f":root {{ --rgb: {rgb}; --rgb2: {rgb2}; --blue: {blue}; --violet: {violet}; }}"
    )


st.html(f"<style>{BASE_CSS}{accent_css(st.session_state.accent)}</style>")


# ============================================================
# HELPERS
# ============================================================

def render_brand():
    model_id = MODELS.get(st.session_state.model_label, "")
    st.html(
        f"""
        <div class="topbar">
            <div class="brand">
                <div class="brand-icon">🏗️</div>
                <div>
                    <div class="brand-name">Technical Debt &amp; Legacy Architect</div>
                    <div class="brand-caption">Review code, diagrams and systems like a senior architect</div>
                </div>
            </div>
            <div class="status"><i></i>Ready <small>{escape(model_id)}</small></div>
        </div>
        """
    )


def greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def get_extension(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def file_label(filename):
    ext = get_extension(filename)
    return LABELS.get(ext, ext.upper() if ext else "File")


def current_model():
    return MODELS[st.session_state.model_label]


def build_system_prompt():
    parts = [
        SYSTEM_PROMPT,
        ROLES.get(st.session_state.role, ""),
        DEPTHS.get(st.session_state.depth, ""),
        MODES.get(st.session_state.mode, ""),
    ]
    return "\n\n".join(p for p in parts if p)


def make_config(json_mode=False, temperature=None):
    return types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        temperature=(
            st.session_state.temperature if temperature is None else temperature
        ),
        response_mime_type="application/json" if json_mode else None,
    )


def text_content(role, text):
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


def detect_material():
    """Pull the 'Material type: ...' line out of the first assistant answer."""
    for m in st.session_state.messages:
        if m["role"] == "assistant" and not m.get("error"):
            found = re.search(r"Material type:\s*\**\s*([^\n*]+)", m.get("text", ""))
            if found:
                return found.group(1).strip()
    return None


# ---------- uploads ----------

def to_file_dict(uploaded):
    ext = get_extension(uploaded.name)
    if ext in IMAGE_EXT:
        kind = "image"
        mime = uploaded.type or f"image/{'jpeg' if ext == 'jpg' else ext}"
    elif ext == "pdf":
        kind, mime = "pdf", "application/pdf"
    else:
        kind, mime = "text", uploaded.type or "text/plain"
    return {
        "name": uploaded.name,
        "label": file_label(uploaded.name),
        "kind": kind,
        "mime": mime,
        "bytes": uploaded.getvalue(),
    }


def build_parts(files, text):
    parts = []
    for f in files:
        if f["kind"] in ("image", "pdf"):
            parts.append(types.Part.from_bytes(data=f["bytes"], mime_type=f["mime"]))
            continue
        try:
            body = f["bytes"].decode("utf-8")
        except UnicodeDecodeError:
            body = f["bytes"].decode("latin-1", errors="replace")
        note = ""
        if len(body) > MAX_TEXT_CHARS:
            body = body[:MAX_TEXT_CHARS]
            note = "\n[File truncated because it was too long]"
        parts.append(
            types.Part.from_text(
                text=(
                    f"\n===== FILE: {f['name']} ({f['label']}) =====\n"
                    f"{body}{note}\n===== END FILE =====\n"
                )
            )
        )
    if text:
        parts.append(types.Part.from_text(text=text))
    elif files:
        parts.append(
            types.Part.from_text(
                text=(
                    "Analyze the attached material. First identify the material "
                    "type, then give only the relevant sections."
                )
            )
        )
    return parts


# ---------- rendering ----------

def render_message(message):
    avatar = "🏗️" if message["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(message["role"], avatar=avatar):
        for f in message.get("files", []):
            if f["kind"] == "image" and f.get("bytes"):
                st.image(f["bytes"], width=440, caption=f["name"])
            else:
                st.html(
                    f'<span class="file-chip">📎 {escape(f["name"])} '
                    f'<em>{escape(f["label"])}</em></span>'
                )
        if message.get("text"):
            st.markdown(message["text"])


def radar_svg(dimensions):
    points = []
    for d in dimensions:
        try:
            score = max(0, min(100, int(d.get("score"))))
        except (TypeError, ValueError):
            continue
        points.append((str(d.get("name", "")), score))
    if len(points) < 3:
        return ""

    cx, cy, radius = 165, 150, 92
    n = len(points)

    def pos(i, frac):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        return cx + radius * frac * math.cos(angle), cy + radius * frac * math.sin(angle)

    out = ['<svg viewBox="0 0 330 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Health radar">']
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pos(i, ring) for i in range(n)))
        out.append(f'<polygon class="rg" points="{pts}"/>')
    for i in range(n):
        x, y = pos(i, 1.0)
        out.append(f'<line class="ra" x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}"/>')
    shape = " ".join(
        f"{x:.1f},{y:.1f}" for x, y in (pos(i, s / 100) for i, (_, s) in enumerate(points))
    )
    out.append(f'<polygon class="rv" points="{shape}"/>')
    for i, (name, s) in enumerate(points):
        x, y = pos(i, s / 100)
        out.append(f'<circle class="rd" cx="{x:.1f}" cy="{y:.1f}" r="3.5"/>')
        lx, ly = pos(i, 1.2)
        anchor = "middle" if abs(lx - cx) < 8 else ("start" if lx > cx else "end")
        out.append(
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}">{escape(name)} {s}</text>'
        )
    out.append("</svg>")
    return f'<div class="radar">{"".join(out)}</div>'


def render_board(items):
    columns = {p: [] for p in PRIORITY_META}
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        priority = str(item.get("priority", "P2")).upper()[:2]
        if priority not in columns:
            priority = "P2"
        columns[priority].append(item)
    html_cols = []
    for priority, (label, color) in PRIORITY_META.items():
        cards = []
        for item in columns[priority]:
            effort = str(item.get("effort", "")).upper()[:1]
            effort_text = {"S": "Small effort", "M": "Medium effort", "L": "Large effort"}.get(effort, "")
            tag = f"<br><i>{effort_text}</i>" if effort_text else ""
            cards.append(f'<div class="ditem">{escape(str(item.get("title", "")))}{tag}</div>')
        body = "".join(cards) or '<div class="bempty">Nothing here</div>'
        html_cols.append(
            f'<div class="bcol" style="--pc:{color}">'
            f'<div class="bhead"><b><em>{priority}</em>{label}</b><span>{len(columns[priority])}</span></div>'
            f'<div class="bbody">{body}</div></div>'
        )
    st.html(f'<div class="board">{"".join(html_cols)}</div>')


def render_scorecard(sc):
    try:
        overall = max(0, min(100, int(sc.get("overall_score", 0))))
    except (TypeError, ValueError):
        overall = 0
    color = "#4ade9b" if overall >= 75 else "#ffb547" if overall >= 50 else "#ff6b6b"
    st.html(
        f"""
        <div class="score-wrap">
            <div class="score-ring" style="--c:{color};--p:{overall}">
                <div class="score-inner">
                    <span>{overall}</span><small>Grade {escape(str(sc.get('grade', '-')))}</small>
                </div>
            </div>
            <div class="score-verdict">{escape(str(sc.get('verdict', '')))}</div>
        </div>
        """
    )

    dimensions = sc.get("dimensions", []) or []
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        for d in dimensions:
            score = d.get("score")
            if score is None:
                continue
            try:
                score = max(0, min(100, int(score)))
            except (TypeError, ValueError):
                continue
            st.progress(
                score / 100,
                text=f"{d.get('name', '')}: {score}/100. {d.get('note', '')}",
            )
    with right:
        radar = radar_svg(dimensions)
        if radar:
            st.html(radar)

    items = sc.get("debt_items") or []
    if items:
        st.html('<div class="section-label">Debt board</div>')
        render_board(items)

    risks = (sc.get("top_risks") or [])[:3]
    wins = (sc.get("quick_wins") or [])[:3]
    if risks or wins:
        c1, c2 = st.columns(2)
        with c1:
            if risks:
                st.html('<div class="section-label">Top risks</div>')
                for risk in risks:
                    st.html(f'<div class="risk">⚠️ {escape(str(risk))}</div>')
        with c2:
            if wins:
                st.html('<div class="section-label">Quick wins</div>')
                for win in wins:
                    st.html(f'<div class="win">✅ {escape(str(win))}</div>')


# ============================================================
# GEMINI
# ============================================================

def stream_answer(contents, usage):
    """Stream an answer. If the chosen model fails before producing any text,
    quietly try the fallback models."""
    chosen = current_model()
    candidates = [chosen] + [m for m in FALLBACK_MODELS if m != chosen]
    last_error = None

    for model in candidates:
        emitted = False
        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=make_config(),
            ):
                meta = getattr(chunk, "usage_metadata", None)
                if meta and getattr(meta, "total_token_count", None):
                    usage["tokens"] = meta.total_token_count
                if chunk.text:
                    emitted = True
                    yield chunk.text
            if emitted:
                if model != chosen:
                    usage["fallback"] = model
                return
            last_error = "The model returned an empty answer."
        except Exception as error:
            last_error = error
            if emitted:
                usage["error"] = True
                yield f"\n\n⚠️ **The answer was interrupted.** Details: `{error}`"
                return

    usage["error"] = True
    yield (
        "⚠️ **I couldn't process that request.**\n\n"
        f"Details: `{last_error}`\n\n"
        "Use **Regenerate** to retry, pick another model in the sidebar, "
        "or shorten the input."
    )


def generate_text(prompt, json_mode=False):
    contents = st.session_state.history + [text_content("user", prompt)]
    response = client.models.generate_content(
        model=current_model(),
        contents=contents,
        config=make_config(json_mode=json_mode, temperature=0.2),
    )
    return response.text or ""


def run_turn(text, files):
    st.session_state.last_turn = {"text": text, "files": files}
    meta_files = [
        {
            "name": f["name"],
            "label": f["label"],
            "kind": f["kind"],
            "bytes": f["bytes"] if f["kind"] == "image" else None,
        }
        for f in files
    ]
    user_message = {"role": "user", "text": text, "files": meta_files}
    st.session_state.messages.append(user_message)
    render_message(user_message)

    parts = build_parts(files, text)
    user_content = types.Content(role="user", parts=parts)
    contents = st.session_state.history + [user_content]
    usage = {"tokens": 0, "error": False, "fallback": None}

    with st.chat_message("assistant", avatar="🏗️"):
        with st.spinner("Analyzing..."):
            answer = st.write_stream(stream_answer(contents, usage))
        if usage["fallback"]:
            st.caption(f"Answered by {usage['fallback']} because the selected model was unavailable.")

    st.session_state.messages.append(
        {"role": "assistant", "text": answer, "files": [], "error": usage["error"]}
    )
    if not usage["error"]:
        st.session_state.history.append(user_content)
        st.session_state.history.append(text_content("model", answer))
        st.session_state.tokens += usage["tokens"]
        # Stale after a new analysis.
        st.session_state.report = None
        st.session_state.scorecard = None
        st.session_state.summary_sent = False
        if st.session_state.auto_score:
            with st.spinner("Updating scorecard..."):
                try:
                    st.session_state.scorecard = generate_scorecard()
                except Exception:
                    st.session_state.scorecard = None


def parse_json_object(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return JSON.")
    return json.loads(raw[start:end + 1])


def generate_scorecard():
    return parse_json_object(generate_text(SCORECARD_PROMPT, json_mode=True))


def pop_last_turn():
    """Remove the last user+assistant pair from the UI and from Gemini's history."""
    msgs = st.session_state.messages
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant":
        return False
    was_error = msgs[-1].get("error", False)
    del msgs[-2:]
    if not was_error and len(st.session_state.history) >= 2:
        del st.session_state.history[-2:]
    st.session_state.report = None
    st.session_state.scorecard = None
    st.session_state.summary_sent = False
    return True


# ============================================================
# TELEGRAM
# ============================================================

def split_telegram_message(text, max_length=3900):
    text = text.strip()
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)
        if split_at < 100:
            split_at = text.rfind(" ", 0, max_length)
        if split_at < 100:
            split_at = max_length
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        for chunk in split_telegram_message(text):
            payload = urllib.parse.urlencode(
                {"chat_id": TELEGRAM_CHAT_ID, "text": chunk}
            ).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok", False):
                return False, result.get("description", "Telegram API error.")
        return True, "Report sent successfully."
    except Exception as error:
        return False, str(error)


def send_telegram_document(text, filename):
    """Send the report as an .md file attachment (multipart upload)."""
    try:
        boundary = "----architect" + datetime.now().strftime("%Y%m%d%H%M%S%f")
        crlf = b"\r\n"
        body = b""
        body += f"--{boundary}".encode() + crlf
        body += b'Content-Disposition: form-data; name="chat_id"' + crlf + crlf
        body += TELEGRAM_CHAT_ID.encode() + crlf
        body += f"--{boundary}".encode() + crlf
        body += (
            f'Content-Disposition: form-data; name="document"; filename="{filename}"'
        ).encode() + crlf
        body += b"Content-Type: text/markdown" + crlf + crlf
        body += text.encode("utf-8") + crlf
        body += f"--{boundary}--".encode() + crlf
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok", False):
            return False, result.get("description", "Telegram API error.")
        return True, "Document sent."
    except Exception as error:
        return False, str(error)


def send_summary_to_telegram():
    """Generate the report from the whole conversation and send it."""
    try:
        report = generate_text(SUMMARY_PROMPT)
    except Exception as error:
        return False, f"Couldn't generate the report: {error}"
    if not report.strip():
        return False, "The report came back empty. Try again."
    st.session_state.report = report
    ok, info = send_telegram_message(report)
    if ok and st.session_state.tg_attach:
        ok, info = send_telegram_document(
            report, f"architect-report-{datetime.now():%Y%m%d-%H%M}.md"
        )
    st.session_state.summary_sent = ok
    return ok, info


def telegram_action():
    with st.spinner("Writing the report and sending it to Telegram..."):
        ok, info = send_summary_to_telegram()
    if ok:
        st.toast("Report sent to your Telegram chat", icon="✅")
    else:
        st.error(f"Telegram error: {info}")


def build_transcript():
    lines = [
        "# Architecture Session",
        f"*{st.session_state.name}, {datetime.now():%Y-%m-%d %H:%M}*",
        "",
    ]
    for m in st.session_state.messages:
        who = "You" if m["role"] == "user" else "Architect"
        lines.append(f"## {who}")
        for f in m.get("files", []):
            lines.append(f"- Attached: {f['name']} ({f['label']})")
        lines.append(m.get("text", ""))
        lines.append("")
    return "\n".join(lines)


# ============================================================
# ONBOARDING
# ============================================================

if not st.session_state.onboarded:
    render_brand()

    st.html(
        """
        <div class="hero">
            <div>
                <h1>Understand legacy systems before you touch them.</h1>
                <p>
                    Drop in source code, architecture diagrams, schemas, API specs, logs or
                    configs. Get a prioritized technical-debt review, security findings,
                    refactored code and an incremental modernization plan.
                </p>
                <div class="hero-tags">
                    <span class="tag">⚡ Streaming answers</span>
                    <span class="tag">📎 Multi-file upload</span>
                    <span class="tag">📊 Debt board and radar</span>
                    <span class="tag">📨 Telegram reports</span>
                </div>
            </div>
            <div class="hero-art">
                <svg viewBox="0 0 380 300" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0" stop-color="#5eb0ff"/><stop offset="1" stop-color="#8b7bff"/>
                        </linearGradient>
                    </defs>
                    <path class="flow" d="M110 70 L190 70 L190 130" stroke="#5eb0ff" stroke-width="2"/>
                    <path class="flow" d="M270 70 L190 70" stroke="#5eb0ff" stroke-width="2"/>
                    <path class="flow" d="M190 190 L190 230" stroke="#36e0d0" stroke-width="2"/>
                    <path class="flow" d="M110 250 L270 250" stroke="#ffb547" stroke-width="2"/>
                    <rect x="30" y="44" width="100" height="52" rx="12" fill="#0f2139" stroke="#2c4c78"/>
                    <text x="80" y="75" text-anchor="middle" fill="#bcdcff" font-size="13" font-weight="700" font-family="Manrope, sans-serif">Legacy UI</text>
                    <rect x="250" y="44" width="100" height="52" rx="12" fill="#0f2139" stroke="#2c4c78"/>
                    <text x="300" y="75" text-anchor="middle" fill="#bcdcff" font-size="13" font-weight="700" font-family="Manrope, sans-serif">REST API</text>
                    <rect x="120" y="130" width="140" height="60" rx="14" fill="url(#g1)"/>
                    <text x="190" y="166" text-anchor="middle" fill="#061225" font-size="14" font-weight="800" font-family="Manrope, sans-serif">Monolith</text>
                    <rect x="30" y="224" width="100" height="52" rx="12" fill="#0f2139" stroke="#ffb547"/>
                    <text x="80" y="255" text-anchor="middle" fill="#ffd699" font-size="13" font-weight="700" font-family="Manrope, sans-serif">Tech debt</text>
                    <rect x="250" y="224" width="100" height="52" rx="12" fill="#0f2139" stroke="#36e0d0"/>
                    <text x="300" y="255" text-anchor="middle" fill="#9bf1e8" font-size="13" font-weight="700" font-family="Manrope, sans-serif">Database</text>
                    <circle cx="260" cy="130" r="14" fill="#ff6b6b"/>
                    <text x="260" y="135" text-anchor="middle" fill="#fff" font-size="14" font-weight="800" font-family="Manrope, sans-serif">!</text>
                </svg>
            </div>
        </div>
        <div class="stats-strip">
            <div class="stat-big"><b>20+</b><span>Languages and file types</span></div>
            <div class="stat-big"><b>P0 to P3</b><span>Prioritized debt</span></div>
            <div class="stat-big"><b>5 phases</b><span>Modernization roadmap</span></div>
            <div class="stat-big"><b>1 click</b><span>Report to Telegram</span></div>
        </div>
        <div class="grid4">
            <div class="cell"><div class="ico">💻</div><b>Code intelligence</b>
                <span>Python, Java, C#, JS/TS, Go, Rust, C/C++ and more.</span></div>
            <div class="cell"><div class="ico">📐</div><b>Architecture vision</b>
                <span>C4, UML, sequence and deployment diagrams from screenshots.</span></div>
            <div class="cell"><div class="ico">🗄️</div><b>Data and APIs</b>
                <span>SQL schemas, ER diagrams, OpenAPI and GraphQL.</span></div>
            <div class="cell"><div class="ico">🚨</div><b>Debug and modernize</b>
                <span>Stack traces, logs, Docker, Kubernetes and CI/CD.</span></div>
        </div>
        <div class="panel-title">Start your workspace</div>
        <div class="panel-sub">Your experience level sets how much each answer explains.</div>
        """
    )

    with st.form("onboarding_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Your name", placeholder="e.g. Sai Sravan")
        with c2:
            role = st.selectbox("Your experience level", list(ROLES))
        b1, b2 = st.columns([3, 1])
        with b1:
            submitted = st.form_submit_button(
                "Open workspace", width="stretch", type="primary"
            )
        with b2:
            guest = st.form_submit_button("Continue as guest", width="stretch")

    if submitted or guest:
        clean = name.strip()
        if submitted and not clean:
            st.warning("Enter your name, or choose Continue as guest.")
        else:
            reset_session()
            st.session_state.name = clean or "Guest"
            st.session_state.role = role
            st.session_state.onboarded = True
            st.rerun()

    st.html('<div class="footer">Technical Debt &amp; Legacy Architect</div>')
    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

has_material = len(st.session_state.history) > 0

with st.sidebar:
    st.html(
        f"""
        <div class="side-card">
            <div class="avatar">{escape(st.session_state.name[:1].upper())}</div>
            <div>
                <div class="side-user">{escape(st.session_state.name)}</div>
                <div class="side-role">{escape(st.session_state.role)}</div>
            </div>
        </div>
        """
    )
    detected = detect_material()
    if detected:
        st.html(f'<div class="detected">🔎 {escape(detected)}</div>')

    st.html('<div class="side-h">Analysis settings</div>')
    st.selectbox("Focus", list(MODES), key="mode")
    st.select_slider("Depth", options=list(DEPTHS), key="depth")
    st.selectbox("Model", list(MODELS), key="model_label")
    st.slider(
        "Creativity",
        0.0, 1.0, step=0.1, key="temperature",
        help="Lower is more precise and consistent. Higher is more exploratory.",
    )

    st.html('<div class="side-h">Insights</div>')
    if st.button(
        "📨 Send summary to Telegram",
        key="tg_side",
        type="primary",
        width="stretch",
        disabled=not has_material,
    ):
        telegram_action()
    st.toggle("Attach the report as a .md file", key="tg_attach")

    if st.button("📊 Debt scorecard", width="stretch", disabled=not has_material):
        with st.spinner("Scoring..."):
            try:
                st.session_state.scorecard = generate_scorecard()
            except Exception as error:
                st.session_state.scorecard = None
                st.error(f"Couldn't build the scorecard: {error}")
    st.toggle("Update the scorecard after every answer", key="auto_score")

    if st.button("📝 Generate report", width="stretch", disabled=not has_material):
        with st.spinner("Writing report..."):
            try:
                st.session_state.report = generate_text(SUMMARY_PROMPT)
                st.session_state.summary_sent = False
            except Exception as error:
                st.error(f"Couldn't generate the report: {error}")

    if st.session_state.report:
        st.download_button(
            "⬇️ Download report (.md)",
            data=st.session_state.report,
            file_name=f"architect-report-{datetime.now():%Y%m%d-%H%M}.md",
            mime="text/markdown",
            width="stretch",
        )
    if st.session_state.scorecard:
        st.download_button(
            "⬇️ Download scorecard (.json)",
            data=json.dumps(st.session_state.scorecard, indent=2),
            file_name=f"architect-scorecard-{datetime.now():%Y%m%d-%H%M}.json",
            mime="application/json",
            width="stretch",
        )
    if st.session_state.summary_sent:
        st.html('<div class="telegram-ok">✓ Latest report delivered to your Telegram chat.</div>')

    st.html('<div class="side-h">Session</div>')
    user_turns = sum(1 for m in st.session_state.messages if m["role"] == "user")
    st.html(
        f"""
        <div class="stat-row">
            <div class="stat"><b>{user_turns}</b><span>Questions</span></div>
            <div class="stat"><b>{st.session_state.tokens:,}</b><span>Tokens used</span></div>
        </div>
        """
    )
    if st.session_state.messages:
        st.download_button(
            "💾 Download conversation",
            data=build_transcript(),
            file_name=f"architect-session-{datetime.now():%Y%m%d-%H%M}.md",
            mime="text/markdown",
            width="stretch",
        )
    if st.button("🧹 Clear conversation", width="stretch"):
        reset_session()
        st.rerun()
    if st.button("🚪 Change user", width="stretch"):
        reset_session()
        st.session_state.onboarded = False
        st.rerun()

    st.html('<div class="side-h">Appearance</div>')
    st.selectbox("Accent color", list(ACCENTS), key="accent")


# ============================================================
# WORKSPACE
# ============================================================

render_brand()

tg_left, tg_right = st.columns([6, 2], vertical_alignment="center")
with tg_left:
    st.caption(
        "Attach code, diagrams, PDFs or logs, then ask anything. "
        "When you're done, send the full report to Telegram."
    )
with tg_right:
    if st.button(
        "📨 Telegram Report",
        key="tg_main",
        type="primary",
        width="stretch",
        disabled=not has_material,
    ):
        telegram_action()

submission = st.chat_input(
    "Ask a question, paste code, or attach files (code, diagrams, PDFs, logs)...",
    accept_file="multiple",
    file_type=ALLOWED_TYPES,
)

if submission:
    new_text = (submission.text or "").strip()
    new_files = [to_file_dict(f) for f in (submission.files or [])]
    if sum(len(f["bytes"]) for f in new_files) > MAX_UPLOAD_BYTES:
        st.warning("Those files are over 18 MB together. Attach fewer or smaller files.")
    elif new_text or new_files:
        st.session_state.pending = {"text": new_text, "files": new_files}

pending = st.session_state.pending

if st.session_state.scorecard:
    with st.expander("📊 Technical debt scorecard", expanded=True):
        render_scorecard(st.session_state.scorecard)

# ---------- empty state ----------
if not st.session_state.messages and not pending:
    st.html(
        f"""
        <div class="welcome">
            <h2>{greeting()}, {escape(st.session_state.name)}. What are we analyzing?</h2>
            <p>
                Attach code, a screenshot of an architecture diagram, a schema, an API spec,
                an error log or a config file using the box below, or paste code straight in.
                Want to see it work first? Run one of the samples.
            </p>
            <div class="dropzone">📎 Use the box at the bottom to attach files or paste code</div>
        </div>
        <div class="section-label">Try a sample</div>
        """
    )
    demo_cols = st.columns(len(DEMOS))
    for col, demo in zip(demo_cols, DEMOS):
        with col:
            with st.container(key=f"demo_{demo['key']}"):
                st.html(
                    f'<div class="demo-ico">{demo["icon"]}</div>'
                    f'<div class="demo-title">{escape(demo["title"])}</div>'
                    f'<div class="demo-desc">{escape(demo["desc"])}</div>'
                )
                if st.button("Run review", key=f"run_{demo['key']}", width="stretch"):
                    st.session_state.pending = {"text": demo["prompt"], "files": []}
                    st.rerun()

    st.html(
        """
        <div class="section-label">What you can ask</div>
        <div class="grid4">
            <div class="cell"><div class="ico">🔍</div><b>Find technical debt</b>
                <span>Prioritized P0 to P3 with fixes.</span></div>
            <div class="cell"><div class="ico">🔐</div><b>Audit security</b>
                <span>Injection, secrets, auth and OWASP mapping.</span></div>
            <div class="cell"><div class="ico">🛠️</div><b>Refactor code</b>
                <span>Get improved code, not just advice.</span></div>
            <div class="cell"><div class="ico">🚀</div><b>Plan modernization</b>
                <span>Phased, incremental, low-risk roadmaps.</span></div>
        </div>
        """
    )
else:
    for message in st.session_state.messages:
        render_message(message)

# ---------- process a queued turn ----------
if pending:
    st.session_state.pending = None
    run_turn(pending["text"], pending["files"])
    st.rerun()

# ---------- actions on the latest answer ----------
messages = st.session_state.messages
if messages and messages[-1]["role"] == "assistant":
    last = messages[-1]
    with st.container(key="actions_row"):
        a1, a2, a3, _ = st.columns([1.5, 1.2, 1.2, 5])
        with a1:
            if st.session_state.last_turn and st.button(
                "🔄 Regenerate", key="act_regen", width="stretch"
            ):
                turn = st.session_state.last_turn
                if pop_last_turn():
                    st.session_state.pending = turn
                    st.rerun()
        with a2:
            if st.button("↩️ Undo", key="act_undo", width="stretch"):
                if pop_last_turn():
                    st.session_state.last_turn = None
                    st.rerun()
        with a3:
            with st.popover("📋 Copy", width="stretch"):
                st.caption("Use the copy icon in the corner of the box.")
                st.code(last.get("text", ""), language="markdown")

# ---------- follow-up chips ----------
if messages:
    st.html('<div class="section-label">Keep going</div>')
    cols = st.columns(len(FOLLOW_UPS))
    for col, (label, prompt) in zip(cols, FOLLOW_UPS):
        with col:
            if st.button(label, key=f"chip_{label}", width="stretch"):
                st.session_state.pending = {"text": prompt, "files": []}
                st.rerun()

st.html(
    '<div class="footer">AI can make mistakes. Verify important findings before '
    "changing production systems.</div>"
)