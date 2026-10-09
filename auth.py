"""
auth.py
--------
Phase 1 authentication layer.

UI me user "Username" type karta hai, lekin Supabase Auth email+password pe
kaam karta hai. Is file ka kaam sirf itna hai: username -> email identity map
karna aur Supabase se login/logout karana.

Username structure baad me change hoga -> tab sirf `username_to_identity()`
edit karni padegi, baaki app ko haath lagane ki zarurat nahi.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st
from supabase import Client, create_client


DEFAULT_IDENTITY_DOMAIN = "emiza.local"


@dataclass
class AuthResult:
    ok: bool
    username: str | None = None
    session: object | None = None
    user: object | None = None
    error: str | None = None


def _get_secret(key: str) -> str | None:
    """Streamlit secrets first, environment variable as fallback."""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key)


def get_client() -> Client:
    """Create one Supabase client per Streamlit session."""
    if "_supabase_client" not in st.session_state:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_ANON_KEY")

        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_ANON_KEY missing. "
                "Add them to .streamlit/secrets.toml or environment variables."
            )

        st.session_state["_supabase_client"] = create_client(
            url, key
        )

    return st.session_state["_supabase_client"]


def username_to_identity(username: str) -> str:
    """
    Map a user-facing username to the Supabase auth identity (an email).

    - "amit"              -> "amit@emiza.local"
    - "amit@emiza.com"    -> "amit@emiza.com"   (already an identity)
    """
    username = (username or "").strip().lower()
    if not username:
        return ""
    if "@" in username:
        return username
    domain = _get_secret("IDENTITY_DOMAIN") or DEFAULT_IDENTITY_DOMAIN
    return f"{username}@{domain}"


def display_username(identity: str) -> str:
    """Reverse map: identity -> what we show on screen."""
    if not identity:
        return ""
    domain = _get_secret("IDENTITY_DOMAIN") or DEFAULT_IDENTITY_DOMAIN
    if identity.endswith(f"@{domain}"):
        return identity.split("@", 1)[0]
    return identity


def sign_in(username: str, password: str) -> AuthResult:
    """Authenticate through Supabase. Generic error message on any failure."""
    generic = "Invalid username or password"

    if not username or not password:
        return AuthResult(ok=False, error=generic)

    identity = username_to_identity(username)

    try:
        client = get_client()
    except RuntimeError as exc:
        return AuthResult(ok=False, error=str(exc))

    try:
        res = client.auth.sign_in_with_password(
            {"email": identity, "password": password}
        )
    except Exception:
        return AuthResult(ok=False, error=generic)

    if not getattr(res, "session", None) or not getattr(res, "user", None):
        return AuthResult(ok=False, error=generic)

    return AuthResult(
        ok=True,
        username=display_username(getattr(res.user, "email", identity)),
        session=res.session,
        user=res.user,
    )


def sign_out() -> None:
    try:
        get_client().auth.sign_out()
    except Exception:
        pass


# =========================================================
# REFRESH FIX
# =========================================================

def restore_session() -> bool:
    """
    Browser refresh par call hoti hai.

    Supabase client apni memory me access_token rakhta hai
    jab tak server process chal raha ho.

    Valid session mili  -> session_state set karke True return
    Session nahi mili   -> False return, login page dikhega
    """
    try:
        client  = get_client()
        session = client.auth.get_session()

        if session and session.user:
            email    = getattr(session.user, "email", "") or ""
            username = display_username(email)

            st.session_state.authenticated = True
            st.session_state.username      = username or email
            st.session_state.session       = session
            return True

    except Exception:
        pass

    return False

# =========================================================
# ACTIVITY TRACKING
# =========================================================

from datetime import datetime, timezone

def update_activity(username: str) -> None:
    """Har page render pe last_active update karo."""
    try:
        get_client().table("user_sessions").upsert({
            "username": username,
            "last_active": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass


def is_session_expired(username: str, limit_seconds: int = 600) -> bool:
    """Supabase se check karo — 10 min se zyada idle hai?"""
    try:
        res = get_client().table("user_sessions")\
            .select("last_active")\
            .eq("username", username)\
            .single()\
            .execute()

        if not res.data:
            return True

        last = datetime.fromisoformat(res.data["last_active"])

        # timezone-aware banana
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        diff = (datetime.now(timezone.utc) - last).total_seconds()
        return diff > limit_seconds

    except Exception:
        return False  # error pe logout mat karo
