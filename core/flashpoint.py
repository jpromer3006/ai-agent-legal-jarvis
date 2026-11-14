"""Flashpoint.AI MCP client for JARVIS Immigration.

Flashpoint (https://api.flashpoint.ai/mcp) is a research engine: demographics,
synthetic persona panels, and surveys. Every tool call is paid per call in
USDC on Base through x402, and agents sign in with a wallet signature.

Protocol (verified live on 2026-11-14):
  1. POST /auth/wallet/challenge {address}       -> {nonce, message_to_sign}
  2. personal_sign(message_to_sign)  (EIP-191)
  3. POST /auth/wallet/token {address, nonce, signature} -> {token, expires_in}
  4. POST /mcp  initialize                        -> header Mcp-Session-Id
  5. POST /mcp  tools/call  (Bearer + session)    -> 402 PAYMENT-REQUIRED
  6. x402 client signs an EIP-3009 USDC authorization and retries -> result

Privacy rule: this module only ever sends COMMUNITY level descriptors
(language, neighborhood, procedural topic). Never a person's name, story,
A-number, or immigration status.

Needs in .env ONE of:
                FLASHPOINT_API_KEY=...                 (bearer token from the organizers)
                FLASHPOINT_WALLET_PRIVATE_KEY=0x...    (funded Base wallet, x402)
Never commit .env.
Optional:       FLASHPOINT_MAX_USDC_PER_CALL=1.00
Without a key, every call returns cached results (cache/flashpoint) or a
clearly labeled offline sample, so the UI still runs for design and demo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.flashpoint")

BASE_URL = os.getenv("FLASHPOINT_BASE_URL", "https://api.flashpoint.ai")
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache" / "flashpoint"
LEDGER_FILE = ROOT / "cache" / "flashpoint_ledger.json"
TOKEN_FILE = ROOT / "cache" / "flashpoint_token.json"      # OAuth sign in (gitignored)
OAUTH_CLIENT_FILE = ROOT / "cache" / "flashpoint_oauth_client.json"
REDIRECT_PORT = 8765


def load_oauth_token() -> str | None:
    """Token saved by oauth_login(), if present and not expired."""
    try:
        d = json.loads(TOKEN_FILE.read_text())
        if d.get("expires_at") and time.time() > d["expires_at"] - 60:
            return None
        return d.get("access_token")
    except Exception:
        return None


def oauth_login(timeout: int = 240) -> dict:
    """Sign in to Flashpoint in the browser (OAuth 2.1 + PKCE, dynamic client).

    Uses the person's own Flashpoint account (for example Google sign in at
    app.flashpoint.ai), so calls run on that account instead of a wallet.
    """
    import base64 as _b64
    import secrets
    import threading
    import urllib.parse
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import requests

    redirect = f"http://localhost:{REDIRECT_PORT}/callback"
    CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        client = json.loads(OAUTH_CLIENT_FILE.read_text())
    except Exception:
        r = requests.post(f"{BASE_URL}/oauth/register", timeout=20, json={
            "client_name": "JARVIS Immigration", "redirect_uris": [redirect],
            "grant_types": ["authorization_code"], "response_types": ["code"],
            "token_endpoint_auth_method": "none"})
        r.raise_for_status()
        client = r.json()
        OAUTH_CLIENT_FILE.write_text(json.dumps(client))

    verifier = secrets.token_urlsafe(64)
    challenge = _b64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>JARVIS is connected to Flashpoint.AI. You can close this tab.</h2>".encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("localhost", REDIRECT_PORT), _H)
    srv.timeout = timeout
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    url = f"{BASE_URL}/oauth/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "resource": f"{BASE_URL}/mcp"})
    webbrowser.open(url)
    t.join(timeout)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"Sign in not completed: {got.get('error', 'no code received')}. URL: {url}")
    tk = requests.post(f"{BASE_URL}/oauth/token", timeout=20, data={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect,
        "client_id": client["client_id"], "code_verifier": verifier})
    tk.raise_for_status()
    tk = tk.json()
    tk["expires_at"] = time.time() + int(tk.get("expires_in", 3600))
    TOKEN_FILE.write_text(json.dumps(tk))
    return {"ok": True, "expires_in": tk.get("expires_in")}

# Approximate list prices (USDC) from the organizers and llms.txt
PRICES = {"chat": 0.01, "demographics": 0.05, "presentation": 0.25,
          "tool_survey": 0.50, "tool_qual": 0.50, "panel": 0.60}


def _parse_mcp_body(text: str) -> dict:
    """MCP over streamable HTTP answers with SSE ("data: {...}") or plain JSON."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    data_lines = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
    for line in reversed(data_lines):
        try:
            msg = json.loads(line)
            if "result" in msg or "error" in msg:
                return msg
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Unparseable MCP response: {text[:200]}")


def _result_text(msg: dict) -> str:
    """Flatten an MCP tools/call result into text."""
    if "error" in msg:
        return f"ERROR: {msg['error'].get('message', msg['error'])}"
    res = msg.get("result", {})
    if res.get("structuredContent"):
        return json.dumps(res["structuredContent"], ensure_ascii=False)
    parts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
    return "\n".join(parts)


@dataclass
class FlashpointResult:
    tool: str
    args: dict
    text: str
    ok: bool
    source: str            # "live" | "cache" | "offline"
    cost_usdc: float = 0.0
    seconds: float = 0.0
    data: Any = None       # parsed JSON when the text is JSON

    def __post_init__(self):
        if self.data is None:
            try:
                self.data = json.loads(self.text)
            except (json.JSONDecodeError, TypeError):
                self.data = None


@dataclass
class FlashpointClient:
    private_key: str | None = None
    max_usdc_per_call: float = 1.0
    log: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.private_key = self.private_key or os.getenv("FLASHPOINT_WALLET_PRIVATE_KEY") or None
        self.api_key = os.getenv("FLASHPOINT_API_KEY") or load_oauth_token() or None
        self.max_usdc_per_call = float(os.getenv("FLASHPOINT_MAX_USDC_PER_CALL",
                                                 self.max_usdc_per_call))
        self._token: str | None = None
        self._token_exp: float = 0
        self._session_id: str | None = None
        self._http = None
        self._address: str | None = None
        self._rpc_id = 0

    # ------------------------------------------------------------ status
    @property
    def live(self) -> bool:
        if not (self.private_key or os.getenv("FLASHPOINT_API_KEY")):
            self.api_key = load_oauth_token()     # pick up a fresh sign in
        return bool(self.private_key or self.api_key)

    @property
    def mode(self) -> str:
        if os.getenv("FLASHPOINT_API_KEY"):
            return "api key"
        if self.api_key:
            return "signed in"
        if self.private_key:
            return "wallet x402"
        return "offline"

    @property
    def address(self) -> str | None:
        if self._address is None and self.private_key:
            try:
                from eth_account import Account
                self._address = Account.from_key(self.private_key).address
            except Exception as e:  # pragma: no cover
                self._note(f"wallet key unreadable: {e}")
        return self._address

    def spent_usdc(self) -> float:
        return round(sum(e.get("cost", 0) for e in _read_ledger()), 2)

    def _note(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {msg}")
        logger.info(msg)

    # ------------------------------------------------------------ auth
    def _ensure_session(self) -> None:
        import requests
        from eth_account import Account
        from eth_account.messages import encode_defunct

        if self._token and time.time() < self._token_exp - 120 and self._http:
            return

        if self.private_key:
            acct = Account.from_key(self.private_key)
            if not self.api_key:
                ch = requests.post(f"{BASE_URL}/auth/wallet/challenge",
                                   json={"address": acct.address}, timeout=20)
                ch.raise_for_status()
                ch = ch.json()
                sig = acct.sign_message(encode_defunct(text=ch["message_to_sign"])).signature.hex()
                sig = sig if sig.startswith("0x") else "0x" + sig
                tk = requests.post(f"{BASE_URL}/auth/wallet/token",
                                   json={"address": acct.address, "nonce": ch["nonce"],
                                         "signature": sig}, timeout=20)
                tk.raise_for_status()
                tk = tk.json()
                self._token = tk["token"]
                self._token_exp = time.time() + int(tk.get("expires_in", 3600))
                self._note(f"wallet JWT issued for {acct.address[:6]}…{acct.address[-4:]}")
            # x402 aware session: signs EIP-3009 USDC authorizations on a 402
            from x402 import x402ClientSync
            from x402.client_base import max_amount
            from x402.http.clients import x402_requests
            from x402.mechanisms.evm.exact import register_exact_evm_client
            from x402.mechanisms.evm.signers import EthAccountSigner

            payer = x402ClientSync()
            register_exact_evm_client(payer, EthAccountSigner(acct),
                                      policies=[max_amount(int(self.max_usdc_per_call * 1_000_000))])
            http = x402_requests(payer)
        else:
            http = requests.Session()

        if self.api_key:
            self._token = self.api_key
            self._token_exp = time.time() + 86400
            self._note(f"using Flashpoint bearer ({self.mode})")
        http.headers.update({"Authorization": f"Bearer {self._token}",
                             "Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream"})
        init = http.post(f"{BASE_URL}/mcp", timeout=30, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "jarvis-immigration", "version": "1.0"}}})
        init.raise_for_status()
        self._session_id = init.headers.get("mcp-session-id")
        http.headers["Mcp-Session-Id"] = self._session_id
        http.post(f"{BASE_URL}/mcp", timeout=15,
                  json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._http = http
        self._note("MCP session open")

    # ------------------------------------------------------------ calls
    def call(self, tool: str, args: dict, use_cache: bool = True,
             timeout: int = 600) -> FlashpointResult:
        """Call a Flashpoint MCP tool. Cache first, then live, then offline."""
        key = hashlib.sha256(json.dumps([tool, args], sort_keys=True).encode()).hexdigest()[:16]
        cache_file = CACHE_DIR / f"{tool}_{key}.json"
        if use_cache and cache_file.exists():
            cached = json.loads(cache_file.read_text())
            self._note(f"{tool}: cache hit")
            return FlashpointResult(tool, args, cached["text"], True, "cache")

        if not self.live:
            self._note(f"{tool}: no wallet key, offline sample")
            return FlashpointResult(tool, args, offline_sample(tool, args), True, "offline")

        t0 = time.time()
        try:
            self._ensure_session()
            self._rpc_id += 1
            resp = self._http.post(f"{BASE_URL}/mcp", timeout=timeout, json={
                "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
                "params": {"name": tool, "arguments": args}})
            if resp.status_code == 401 and not self.api_key:   # JWT expired: one retry
                self._token = None
                self._ensure_session()
                resp = self._http.post(f"{BASE_URL}/mcp", timeout=timeout, json={
                    "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
                    "params": {"name": tool, "arguments": args}})
            if resp.status_code == 402:
                return FlashpointResult(tool, args,
                                        "Payment not accepted (402). Check the wallet has USDC on Base.",
                                        False, "live", seconds=time.time() - t0)
            resp.raise_for_status()
            text = _result_text(_parse_mcp_body(resp.text))
        except Exception as e:
            self._note(f"{tool}: live call failed ({e})")
            return FlashpointResult(tool, args, f"Flashpoint call failed: {e}", False, "live",
                                    seconds=time.time() - t0)

        secs = time.time() - t0
        paid = "PAYMENT-RESPONSE" in {h.upper() for h in resp.headers} or "X-PAYMENT-RESPONSE" in {h.upper() for h in resp.headers}
        cost = PRICES.get(tool, 0.0) if (paid or not text.startswith("ERROR")) else 0.0
        _append_ledger({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool, "cost": cost,
                        "seconds": round(secs, 1)})
        ok = not text.startswith("ERROR")
        if ok:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"tool": tool, "args": args, "text": text},
                                             ensure_ascii=False, indent=2))
        self._note(f"{tool}: live in {secs:.1f}s (~${cost:.2f})")
        return FlashpointResult(tool, args, text, ok, "live", cost, secs)

    # ------------------------------------------------------------ helpers
    def demographics(self, location: str, question: str | None = None,
                     audience: str | None = None) -> FlashpointResult:
        args = {"location": location}
        if question:
            args["question"] = question
        if audience:
            args["audience"] = audience
        return self.call("demographics", args)

    def survey(self, brief: str, conversation_id: str | None = None,
               survey_id: str | None = None) -> FlashpointResult:
        args: dict = {"brief": brief}
        if conversation_id:
            args["conversation_id"] = conversation_id
        if survey_id:
            args["survey_id"] = survey_id
        return self.call("tool_survey", args)

    def synthetic_panel(self, name: str, n: int, objective: str, survey_id: str,
                        context: str | None = None) -> FlashpointResult:
        args = {"action": "create_and_run", "name": name, "num_respondents": n,
                "research_objective": objective, "survey_id": survey_id}
        if context:
            args["context"] = context
        return self.call("panel", args)

    def panel_status(self, job_id: str) -> FlashpointResult:
        return self.call("panel", {"action": "status", "job_id": job_id}, use_cache=False)


# ---------------------------------------------------------------- ledger
def _read_ledger() -> list[dict]:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []


def _append_ledger(entry: dict) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read_ledger()
    data.append(entry)
    LEDGER_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------- offline
def offline_sample(tool: str, args: dict) -> str:
    """Labeled sample so the HUD renders without a wallet. Never real data."""
    if tool == "demographics":
        return json.dumps({
            "OFFLINE_SAMPLE": True,
            "location": args.get("location"),
            "note": "Offline sample. Add FLASHPOINT_WALLET_PRIVATE_KEY to .env for live Census data.",
            "insights": ["Live mode returns population, age, education, income and language "
                         "distributions for this location from the Census Bureau."],
        })
    return json.dumps({"OFFLINE_SAMPLE": True, "tool": tool,
                       "note": "Offline sample. Live mode calls Flashpoint.AI."})
