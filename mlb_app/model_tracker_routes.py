from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .admin_access import (
    USER_CAPABILITIES,
    access_payload_for_user,
    ensure_owner_admin_role,
    is_configured_admin_email,
    resolve_principal,
    resolve_session_token,
)
from .admin_configuration import get_or_create_directory_profile

from .database import (
    AppDashboardFolder,
    AppDashboardItem,
    AppSession,
    AppLoginHistory,
    AppOAuthIdentity,
    AppOAuthLoginCode,
    AppPasswordResetToken,
    AppUser,
    AppUserDirectoryProfile,
    AppUserPreference,
    create_tables,
    get_engine,
    get_session,
)
from .model_tracker import (
    list_tracker_rows,
    list_tracker_range,
    refresh_tracker_results,
)
from .model_tracker_safe_snapshot import build_tracker_snapshot_safe
from .my_dashboard_dataset_runtime import mlb_business_date

router = APIRouter(tags=["model-tracker", "my-dashboard"])

DASHBOARD_SESSION_COOKIE = "mlb_dashboard_session"
DASHBOARD_SESSION_HOURS = 6
DASHBOARD_OAUTH_STATE_COOKIE = "mlb_dashboard_oauth_state"
DASHBOARD_OAUTH_VERIFIER_COOKIE = "mlb_dashboard_oauth_verifier"
DASHBOARD_OAUTH_STATE_MINUTES = 10
DASHBOARD_OAUTH_CODE_MINUTES = 2
DASHBOARD_PASSWORD_RESET_MINUTES = 30
DASHBOARD_PASSWORD_RESET_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)
FEATURE_CHOICES = [
    "Matchups",
    "Daily Odds",
    "Model Projections",
    "News",
    "Props",
    "Pitchers",
    "Batters",
]
DEFAULT_COMPONENTS = [
    {
        "key": "hitters",
        "title": "My Top Hitters Today",
        "description": "Unique hitter board from Batter vs Arsenal, pitch usage, damage quality, and model context.",
        "source_type": "seeded_component",
    },
    {
        "key": "pitchers",
        "title": "My Top Pitchers Today",
        "description": "Pitcher lean board using K profile, contact suppression, opponent offense, and arsenal context.",
        "source_type": "seeded_component",
    },
    {
        "key": "teams",
        "title": "My Top Teams Today",
        "description": "Team board from model side edge, expected runs, offense profile, and opponent weaknesses.",
        "source_type": "seeded_component",
    },
    {
        "key": "totals",
        "title": "Game total watchlist from projected runs, run environment, and simulation context.",
        "description": "Game total watchlist from projected runs, run environment, and simulation context.",
        "source_type": "seeded_component",
    },
    {
        "key": "overall_players",
        "title": "My Top Overall Players Today",
        "description": "Combined unique player board blending hitter and pitcher model-solver scores.",
        "source_type": "seeded_component",
    },
]
DEFAULT_FILTER_FIELDS = ["search_text", "team", "opponent", "min_score", "max_score", "min_confidence", "pitch_type", "category", "source"]


class DashboardProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    username: str
    password: Optional[str] = None
    feature_interests: List[str] = Field(default_factory=list)
    wants_newsletter: bool = False
    plan_type: Optional[str] = "free"


class DashboardRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    username: str
    password: str = Field(min_length=8, max_length=256)
    feature_interests: List[str] = Field(default_factory=list)
    wants_newsletter: bool = False


class DashboardLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(min_length=1, max_length=256)


class DashboardOAuthExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=20, max_length=512)


class DashboardForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str


class DashboardResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=8, max_length=256)


class DashboardItemCreateRequest(BaseModel):
    folder_id: int
    source_tab: str
    source_type: str
    title: str = Field(min_length=1, max_length=255)
    subtitle: Optional[str] = None
    payload_json: Dict[str, Any]
    filter_json: Optional[Dict[str, Any]] = None
    sort_json: Optional[Dict[str, Any]] = None
    pin_order: Optional[int] = None
    notes: Optional[str] = None


class DashboardFolderCreateRequest(BaseModel):
    folder_name: str
    folder_date: Optional[str] = None
    is_default: bool = False


class DashboardFolderRenameRequest(BaseModel):
    folder_name: str = Field(max_length=255)


class DashboardItemRenameRequest(BaseModel):
    title: str = Field(max_length=255)


def _validated_dashboard_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="Name must be 255 characters or fewer")
    return name



def _session_factory():
    database_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URL") or os.getenv("POSTGRES_URL") or "sqlite:///mlb.db"
    engine = get_engine(database_url)
    create_tables(engine)
    return get_session(engine)



def _target_date(value: Optional[str]) -> str:
    target = (value or mlb_business_date().isoformat())[:10]
    try:
        dt.date.fromisoformat(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {value}") from exc
    return target



def _utcnow() -> dt.datetime:
    return dt.datetime.utcnow()



def _cookie_settings() -> Dict[str, Any]:
    same_site = str(os.getenv("DASHBOARD_COOKIE_SAMESITE", "none") or "none").lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "none"
    secure_default = same_site == "none"
    secure = str(os.getenv("DASHBOARD_COOKIE_SECURE", "1" if secure_default else "0")).lower() in {"1", "true", "yes", "on"}
    if same_site == "none":
        secure = True
    return {
        "httponly": True,
        "samesite": same_site,
        "secure": secure,
        "max_age": DASHBOARD_SESSION_HOURS * 60 * 60,
        "path": "/",
    }



def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()



def _normalize_username(username: str) -> str:
    return (username or "").strip()



def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(derived).decode()}"



def _verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored or "$" not in stored:
        return False
    try:
        _, salt_b64, hash_b64 = stored.split("$", 2)
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(hash_b64.encode())
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False



def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()



def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")



def _frontend_url(path: str = "/my-dashboard") -> str:
    base = str(os.getenv("DASHBOARD_FRONTEND_URL", "https://mlbgpt.com") or "https://mlbgpt.com").rstrip("/")
    return f"{base}/{path.lstrip('/')}"



def _oauth_provider_config(provider: str) -> Optional[Dict[str, str]]:
    provider = str(provider or "").strip().lower()
    definitions = {
        "google": {
            "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "profile_url": "https://openidconnect.googleapis.com/v1/userinfo",
            "scope": "openid email profile",
        },
        "github": {
            "client_id": os.getenv("GITHUB_OAUTH_CLIENT_ID", ""),
            "client_secret": os.getenv("GITHUB_OAUTH_CLIENT_SECRET", ""),
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "profile_url": "https://api.github.com/user",
            "scope": "read:user user:email",
        },
    }
    config = definitions.get(provider)
    if not config or not config["client_id"] or not config["client_secret"]:
        return None
    return config



def _oauth_callback_url(request: Request, provider: str) -> str:
    configured = str(os.getenv("DASHBOARD_OAUTH_CALLBACK_BASE_URL", "") or "").strip().rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/my-dashboard/auth/oauth/{provider}/callback"



def _oauth_state_cookie_settings() -> Dict[str, Any]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": True,
        "max_age": DASHBOARD_OAUTH_STATE_MINUTES * 60,
        "path": "/my-dashboard/auth/oauth",
    }



def _oauth_profile(
    provider: str,
    config: Dict[str, str],
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> Dict[str, str]:
    token_response = requests.post(
        config["token_url"],
        data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        headers={"Accept": "application/json"},
        timeout=12,
    )
    token_response.raise_for_status()
    access_token = (token_response.json() or {}).get("access_token")
    if not access_token:
        raise ValueError("OAuth provider did not return an access token")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "MLBGPT",
    }
    profile_response = requests.get(config["profile_url"], headers=headers, timeout=12)
    profile_response.raise_for_status()
    profile = profile_response.json() or {}

    if provider == "google":
        email = _normalize_email(profile.get("email"))
        if not email or profile.get("email_verified") is not True:
            raise ValueError("Google did not return a verified email")
        subject = str(profile.get("sub") or "")
        username = str(profile.get("name") or email.split("@", 1)[0]).strip()
    else:
        emails_response = requests.get("https://api.github.com/user/emails", headers=headers, timeout=12)
        emails_response.raise_for_status()
        emails = emails_response.json() or []
        verified = [item for item in emails if item.get("verified") and item.get("email")]
        preferred = next((item for item in verified if item.get("primary")), verified[0] if verified else None)
        if not preferred:
            raise ValueError("GitHub did not return a verified email")
        email = _normalize_email(preferred.get("email"))
        subject = str(profile.get("id") or "")
        username = str(profile.get("name") or profile.get("login") or email.split("@", 1)[0]).strip()

    if not subject:
        raise ValueError("OAuth provider did not return an account identifier")
    return {
        "provider": provider,
        "provider_user_id": subject,
        "email": email,
        "username": (username or email.split("@", 1)[0])[:80],
    }



def _ensure_user_active(session, user: AppUser) -> None:
    directory = (
        session.query(AppUserDirectoryProfile)
        .filter(AppUserDirectoryProfile.user_id == user.id)
        .first()
    )
    if directory and (not directory.is_active or directory.is_locked):
        raise HTTPException(status_code=403, detail="This account is inactive or locked")



def _resolve_oauth_user(session, profile: Dict[str, str]) -> tuple[AppUser, AppUserPreference]:
    prefs: Optional[AppUserPreference] = None
    identity = (
        session.query(AppOAuthIdentity)
        .filter(
            AppOAuthIdentity.provider == profile["provider"],
            AppOAuthIdentity.provider_user_id == profile["provider_user_id"],
        )
        .first()
    )
    if identity:
        user = session.query(AppUser).filter(AppUser.id == identity.user_id).first()
        if user is None:
            raise HTTPException(status_code=401, detail="OAuth account is no longer available")
        _ensure_user_active(session, user)
        identity.provider_email = profile["email"]
        identity.updated_at = _utcnow()
    else:
        user = session.query(AppUser).filter(AppUser.email == profile["email"]).first()
        if user is None:
            if is_configured_admin_email(profile["email"]):
                raise HTTPException(
                    status_code=403,
                    detail="The configured owner account must be provisioned before OAuth can be linked.",
                )
            now = _utcnow()
            user = AppUser(
                email=profile["email"],
                username=profile["username"],
                password_hash=None,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
            prefs = AppUserPreference(
                user_id=user.id,
                wants_newsletter=False,
                feature_interests_json=["Matchups", "Model Projections"],
                plan_type="free",
                created_at=now,
                updated_at=now,
            )
            session.add(prefs)
            default_folder = _get_or_create_default_folder(session, user.id)
            _seed_default_dashboard(session, user.id, default_folder.id)
            _get_or_create_today_folder(session, user.id)
        else:
            _ensure_user_active(session, user)
        identity = AppOAuthIdentity(
            user_id=user.id,
            provider=profile["provider"],
            provider_user_id=profile["provider_user_id"],
            provider_email=profile["email"],
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        session.add(identity)

    if prefs is None:
        prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user.id).first()
    if prefs is None:
        now = _utcnow()
        prefs = AppUserPreference(
            user_id=user.id,
            wants_newsletter=False,
            feature_interests_json=[],
            plan_type="free",
            created_at=now,
            updated_at=now,
        )
        session.add(prefs)
    return user, prefs



def _send_password_reset_email(email: str, reset_url: str) -> None:
    host = str(os.getenv("SMTP_HOST", "") or "").strip()
    sender = str(os.getenv("SMTP_FROM_EMAIL", "") or "").strip()
    if not host or not sender:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL are required")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = str(os.getenv("SMTP_USERNAME", "") or "")
    password = str(os.getenv("SMTP_PASSWORD", "") or "")
    use_ssl = str(os.getenv("SMTP_USE_SSL", "0")).lower() in {"1", "true", "yes", "on"}
    use_tls = str(os.getenv("SMTP_USE_TLS", "1")).lower() in {"1", "true", "yes", "on"}

    message = EmailMessage()
    message["Subject"] = "Reset your MLBGPT password"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "A password reset was requested for your MLBGPT account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link expires in {DASHBOARD_PASSWORD_RESET_MINUTES} minutes and can only be used once. "
        "If you did not request this, you can ignore this email."
    )

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=15) as client:
        if use_tls and not use_ssl:
            client.starttls()
        if username:
            client.login(username, password)
        client.send_message(message)



def _resolve_session_token(cookie_token: Optional[str], header_token: Optional[str]) -> Optional[str]:
    return resolve_session_token(cookie_token, header_token)



def _serialize_user(
    user: AppUser,
    prefs: Optional[AppUserPreference],
    access: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_access = access or {
        "role": "user",
        "capabilities": list(USER_CAPABILITIES),
    }
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": resolved_access["role"],
        "capabilities": list(resolved_access["capabilities"]),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "preferences": {
            "wants_newsletter": prefs.wants_newsletter if prefs else False,
            "feature_interests": prefs.feature_interests_json or [],
            "plan_type": prefs.plan_type if prefs else "free",
        },
    }



def _serialize_folder(folder: AppDashboardFolder, items: List[AppDashboardItem]) -> Dict[str, Any]:
    return {
        "id": folder.id,
        "folder_name": folder.folder_name,
        "folder_date": folder.folder_date.isoformat() if folder.folder_date else None,
        "is_default": folder.is_default,
        "created_at": folder.created_at.isoformat() if folder.created_at else None,
        "updated_at": folder.updated_at.isoformat() if folder.updated_at else None,
        "item_count": len(items),
        "items": [_serialize_item(item) for item in items],
    }



def _serialize_item(item: AppDashboardItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "folder_id": item.folder_id,
        "source_tab": item.source_tab,
        "source_type": item.source_type,
        "title": item.title,
        "subtitle": item.subtitle,
        "payload_json": item.payload_json,
        "filter_json": item.filter_json,
        "sort_json": item.sort_json,
        "pin_order": item.pin_order,
        "notes": item.notes,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }



def _build_seed_payload(component: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "component_key": component["key"],
        "title": component["title"],
        "description": component["description"],
        "seeded_from": "current_my_dashboard_page",
        "save_ready": {
            "source_tabs_supported": [
                "Matchups",
                "Daily Odds",
                "Model Projections",
                "News",
                "My Dashboard",
                "Pitcher",
                "Batter",
                "Team",
                "Model Tracker",
            ],
            "available_fields": ["title", "subtitle", "metrics", "reasoning", "game_pk", "entity_id", "entity_type", "notes"],
            "conditions": ["equals", "contains", "min", "max", "in"],
            "max_filters": 10,
            "default_filter_fields": DEFAULT_FILTER_FIELDS,
            "logic_mode": "AND",
        },
    }



def _get_or_create_today_folder(session, user_id: int) -> AppDashboardFolder:
    today = mlb_business_date()
    folder = (
        session.query(AppDashboardFolder)
        .filter(AppDashboardFolder.user_id == user_id, AppDashboardFolder.folder_date == today)
        .order_by(AppDashboardFolder.id.asc())
        .first()
    )
    if folder:
        return folder
    now = _utcnow()
    folder = AppDashboardFolder(
        user_id=user_id,
        folder_name=today.isoformat(),
        folder_date=today,
        is_default=False,
        created_at=now,
        updated_at=now,
    )
    session.add(folder)
    session.flush()
    return folder



def _get_or_create_default_folder(session, user_id: int) -> AppDashboardFolder:
    folder = (
        session.query(AppDashboardFolder)
        .filter(AppDashboardFolder.user_id == user_id, AppDashboardFolder.is_default.is_(True))
        .order_by(AppDashboardFolder.id.asc())
        .first()
    )
    if folder:
        return folder
    now = _utcnow()
    folder = AppDashboardFolder(
        user_id=user_id,
        folder_name="Default Dashboard",
        folder_date=None,
        is_default=True,
        created_at=now,
        updated_at=now,
    )
    session.add(folder)
    session.flush()
    return folder



def _seed_default_dashboard(session, user_id: int, folder_id: int) -> None:
    existing = (
        session.query(AppDashboardItem)
        .filter(AppDashboardItem.user_id == user_id, AppDashboardItem.folder_id == folder_id)
        .count()
    )
    if existing:
        return
    now = _utcnow()
    for index, component in enumerate(DEFAULT_COMPONENTS, start=1):
        session.add(
            AppDashboardItem(
                user_id=user_id,
                folder_id=folder_id,
                source_tab="my-dashboard",
                source_type=component["source_type"],
                title=component["title"],
                subtitle=component["description"],
                payload_json=_build_seed_payload(component),
                filter_json={
                    "default_filter_fields": DEFAULT_FILTER_FIELDS,
                    "max_filters": 10,
                },
                sort_json={"mode": "manual_seed_order", "position": index},
                pin_order=index,
                created_at=now,
                updated_at=now,
            )
        )



def _upsert_preferences(session, user_id: int, request: BaseModel) -> AppUserPreference:
    prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user_id).first()
    now = _utcnow()
    requested_interests = getattr(request, "feature_interests", []) or []
    feature_interests = [choice for choice in requested_interests if choice in FEATURE_CHOICES]
    wants_newsletter = bool(getattr(request, "wants_newsletter", False))
    requested_plan = getattr(request, "plan_type", None)
    if prefs is None:
        prefs = AppUserPreference(
            user_id=user_id,
            wants_newsletter=wants_newsletter,
            feature_interests_json=feature_interests,
            plan_type=requested_plan or "free",
            created_at=now,
            updated_at=now,
        )
        session.add(prefs)
    else:
        prefs.wants_newsletter = wants_newsletter
        prefs.feature_interests_json = feature_interests
        prefs.plan_type = requested_plan or prefs.plan_type or "free"
        prefs.updated_at = now
    return prefs



def _create_session(
    session,
    user_id: int,
    *,
    now: Optional[dt.datetime] = None,
) -> AppSession:
    now = now or _utcnow()
    expires_at = now + dt.timedelta(hours=DASHBOARD_SESSION_HOURS)
    token = secrets.token_urlsafe(32)
    db_session = AppSession(
        user_id=user_id,
        session_token=token,
        expires_at=expires_at,
        created_at=now,
        last_seen_at=now,
    )
    session.add(db_session)
    session.flush()
    return db_session



def _get_active_user(session, token: Optional[str]) -> Optional[AppUser]:
    principal = resolve_principal(session, token)
    if not principal:
        return None
    return session.query(AppUser).filter(AppUser.id == principal.user_id).first()



def _get_workspace_payload(
    session,
    user: AppUser,
    access: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user.id).first()
    default_folder = _get_or_create_default_folder(session, user.id)
    today_folder = _get_or_create_today_folder(session, user.id)
    _seed_default_dashboard(session, user.id, default_folder.id)
    session.flush()

    folders = (
        session.query(AppDashboardFolder)
        .filter(AppDashboardFolder.user_id == user.id)
        .order_by(AppDashboardFolder.is_default.desc(), AppDashboardFolder.folder_date.desc().nullslast(), AppDashboardFolder.id.desc())
        .all()
    )
    items = (
        session.query(AppDashboardItem)
        .filter(AppDashboardItem.user_id == user.id)
        .order_by(AppDashboardItem.folder_id.asc(), AppDashboardItem.pin_order.asc().nullslast(), AppDashboardItem.id.asc())
        .all()
    )
    items_by_folder: Dict[int, List[AppDashboardItem]] = {}
    for item in items:
        items_by_folder.setdefault(item.folder_id, []).append(item)

    return {
        "user": _serialize_user(user, prefs, access),
        "folders": [_serialize_folder(folder, items_by_folder.get(folder.id, [])) for folder in folders],
        "default_folder_id": default_folder.id,
        "today_folder_id": today_folder.id,
        "feature_choices": FEATURE_CHOICES,
        "seeded_components": [component["key"] for component in DEFAULT_COMPONENTS],
    }


def _validated_registration_password(password: Optional[str]) -> str:
    value = str(password or "")
    if len(value) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters.",
        )
    if len(value) > 256:
        raise HTTPException(
            status_code=400,
            detail="Password must be 256 characters or fewer.",
        )
    return value


def _validated_identity(email: str, username: Optional[str] = None) -> tuple[str, Optional[str]]:
    normalized_email = _normalize_email(email)
    normalized_username = _normalize_username(username or "") if username is not None else None
    if not normalized_email or "@" not in normalized_email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if username is not None and not normalized_username:
        raise HTTPException(status_code=400, detail="Username is required")
    return normalized_email, normalized_username


def _verified_login_user(session, email: str, password: Optional[str]) -> AppUser:
    user = session.query(AppUser).filter(AppUser.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.password_hash:
        raise HTTPException(
            status_code=409,
            detail="Account recovery is required before this profile can sign in.",
        )
    if not password:
        raise HTTPException(status_code=401, detail="Password is required")
    if not _verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    directory = (
        session.query(AppUserDirectoryProfile)
        .filter(AppUserDirectoryProfile.user_id == user.id)
        .first()
    )
    if directory and (not directory.is_active or directory.is_locked):
        raise HTTPException(status_code=403, detail="This account is inactive or locked")
    return user


def _provision_new_user(
    session,
    *,
    email: str,
    username: str,
    password: str,
    preferences: BaseModel,
) -> tuple[AppUser, AppUserPreference]:
    if session.query(AppUser).filter(AppUser.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="An account already exists for this email")
    if is_configured_admin_email(email):
        raise HTTPException(
            status_code=403,
            detail=(
                "The configured owner account must be provisioned before its "
                "email is added to MLBGPT_ADMIN_EMAILS."
            ),
        )
    now = _utcnow()
    user = AppUser(
        email=email,
        username=username,
        password_hash=_hash_password(password),
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    prefs = _upsert_preferences(session, user.id, preferences)
    default_folder = _get_or_create_default_folder(session, user.id)
    _seed_default_dashboard(session, user.id, default_folder.id)
    _get_or_create_today_folder(session, user.id)
    return user, prefs


def _issue_dashboard_session(
    session,
    response: Response,
    user: AppUser,
    prefs: Optional[AppUserPreference],
    *,
    verified_login: bool,
    authentication_method: Optional[str] = None,
) -> Dict[str, Any]:
    now = _utcnow()
    if verified_login:
        ensure_owner_admin_role(session, user, verified_at=now)
    db_session = _create_session(session, user.id, now=now)
    directory = get_or_create_directory_profile(session, user.id, actor_user_id=user.id)
    directory.last_login_at = now
    directory.updated_at = now
    session.add(AppLoginHistory(
        user_id=user.id,
        session_id=db_session.id,
        authentication_method=authentication_method or ("password" if verified_login else "password_registration"),
        successful=True,
        created_at=now,
    ))
    access = access_payload_for_user(
        session,
        user,
        session_created_at=db_session.created_at,
    )
    default_folder = _get_or_create_default_folder(session, user.id)
    session.flush()
    response.set_cookie(
        key=DASHBOARD_SESSION_COOKIE,
        value=db_session.session_token,
        **_cookie_settings(),
    )
    return {
        "ok": True,
        "user": _serialize_user(user, prefs, access),
        "default_folder_id": default_folder.id,
        "session_expires_at": db_session.expires_at.isoformat(),
        # Compatibility: current MyDashboard clients also send the session header.
        "session_token": db_session.session_token,
        "cookie_settings": _cookie_settings(),
    }


@router.get("/model-tracker/health")
def model_tracker_health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "component": "model_tracker",
        "persistence": "model_tracker_snapshots",
        "safe_mode": "additive_snapshot_layer",
    }


@router.post("/model-tracker/snapshot")
def model_tracker_snapshot(date: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    target = _target_date(date)
    try:
        Session = _session_factory()
        with Session() as session:
            return build_tracker_snapshot_safe(session, target)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Model Tracker snapshot failed", "error": str(exc)}) from exc


@router.get("/model-tracker")
def model_tracker_list(date: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    target = _target_date(date)
    try:
        Session = _session_factory()
        with Session() as session:
            return list_tracker_rows(session, target)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Model Tracker list failed", "error": str(exc)}) from exc


@router.get("/model-tracker/range")
def model_tracker_range(
    start: str = Query(..., description="Inclusive YYYY-MM-DD start date"),
    end: str = Query(..., description="Inclusive YYYY-MM-DD end date"),
    include_raw: bool = Query(default=False),
) -> Dict[str, Any]:
    try:
        Session = _session_factory()
        with Session() as session:
            return list_tracker_range(session, start, end, include_raw=include_raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Model Tracker range failed", "error": str(exc)}) from exc


@router.get("/model-tracker/game/{game_pk}")
def model_tracker_game(game_pk: int, date: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    target = _target_date(date)
    try:
        Session = _session_factory()
        with Session() as session:
            payload = list_tracker_rows(session, target, game_pk=game_pk)
            payload["game_pk"] = game_pk
            return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Model Tracker game lookup failed", "error": str(exc)}) from exc


@router.post("/model-tracker/results/refresh")
def model_tracker_results_refresh(date: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    target = _target_date(date)
    try:
        Session = _session_factory()
        with Session() as session:
            return refresh_tracker_results(session, target)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"message": "Model Tracker result refresh failed", "error": str(exc)}) from exc


@router.post("/my-dashboard/auth/register")
def my_dashboard_register(
    request: DashboardRegisterRequest,
    response: Response,
) -> Dict[str, Any]:
    email, username = _validated_identity(request.email, request.username)
    Session = _session_factory()
    with Session() as session:
        user, prefs = _provision_new_user(
            session,
            email=email,
            username=username or "",
            password=request.password,
            preferences=request,
        )
        payload = _issue_dashboard_session(
            session,
            response,
            user,
            prefs,
            verified_login=False,
        )
        session.commit()
        return payload


@router.post("/my-dashboard/auth/login")
def my_dashboard_login(
    request: DashboardLoginRequest,
    response: Response,
) -> Dict[str, Any]:
    email, _ = _validated_identity(request.email)
    Session = _session_factory()
    with Session() as session:
        user = _verified_login_user(session, email, request.password)
        prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user.id).first()
        payload = _issue_dashboard_session(
            session,
            response,
            user,
            prefs,
            verified_login=True,
        )
        session.commit()
        return payload


@router.get("/my-dashboard/auth/providers")
def my_dashboard_auth_providers() -> Dict[str, Any]:
    return {
        "providers": {
            provider: {"configured": _oauth_provider_config(provider) is not None}
            for provider in ("google", "github")
        }
    }


@router.get("/my-dashboard/auth/oauth/{provider}")
def my_dashboard_oauth_start(provider: str, request: Request):
    provider = str(provider or "").strip().lower()
    config = _oauth_provider_config(provider)
    if config is None:
        raise HTTPException(status_code=503, detail=f"{provider.title()} sign-in is not configured")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(48)
    redirect_uri = _oauth_callback_url(request, provider)
    authorization_url = f"{config['authorize_url']}?{urlencode({
        'client_id': config['client_id'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': config['scope'],
        'state': state,
        'code_challenge': _pkce_challenge(code_verifier),
        'code_challenge_method': 'S256',
    })}"
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        key=DASHBOARD_OAUTH_STATE_COOKIE,
        value=state,
        **_oauth_state_cookie_settings(),
    )
    response.set_cookie(
        key=DASHBOARD_OAUTH_VERIFIER_COOKIE,
        value=code_verifier,
        **_oauth_state_cookie_settings(),
    )
    return response


@router.get("/my-dashboard/auth/oauth/{provider}/callback")
def my_dashboard_oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    mlb_dashboard_oauth_state: Optional[str] = Cookie(
        default=None,
        alias=DASHBOARD_OAUTH_STATE_COOKIE,
    ),
    mlb_dashboard_oauth_verifier: Optional[str] = Cookie(
        default=None,
        alias=DASHBOARD_OAUTH_VERIFIER_COOKIE,
    ),
):
    provider = str(provider or "").strip().lower()
    config = _oauth_provider_config(provider)
    failure_url = f"{_frontend_url()}?auth_error=oauth"
    if (
        config is None
        or error
        or not code
        or not state
        or not mlb_dashboard_oauth_state
        or not mlb_dashboard_oauth_verifier
        or not hmac.compare_digest(state, mlb_dashboard_oauth_state)
    ):
        response = RedirectResponse(failure_url, status_code=302)
        response.delete_cookie(DASHBOARD_OAUTH_STATE_COOKIE, path="/my-dashboard/auth/oauth")
        response.delete_cookie(DASHBOARD_OAUTH_VERIFIER_COOKIE, path="/my-dashboard/auth/oauth")
        return response

    try:
        profile = _oauth_profile(
            provider,
            config,
            code,
            _oauth_callback_url(request, provider),
            mlb_dashboard_oauth_verifier,
        )
        Session = _session_factory()
        with Session() as session:
            user, prefs = _resolve_oauth_user(session, profile)
            bridge_code = secrets.token_urlsafe(32)
            success_url = f"{_frontend_url()}?oauth_code={quote(bridge_code)}"
            response = RedirectResponse(success_url, status_code=302)
            payload = _issue_dashboard_session(
                session,
                response,
                user,
                prefs,
                verified_login=True,
                authentication_method=f"oauth_{provider}",
            )
            db_session = (
                session.query(AppSession)
                .filter(AppSession.session_token == payload["session_token"])
                .one()
            )
            session.add(
                AppOAuthLoginCode(
                    user_id=user.id,
                    session_id=db_session.id,
                    token_hash=_token_hash(bridge_code),
                    expires_at=_utcnow() + dt.timedelta(minutes=DASHBOARD_OAUTH_CODE_MINUTES),
                    created_at=_utcnow(),
                )
            )
            session.commit()
            response.delete_cookie(DASHBOARD_OAUTH_STATE_COOKIE, path="/my-dashboard/auth/oauth")
            response.delete_cookie(DASHBOARD_OAUTH_VERIFIER_COOKIE, path="/my-dashboard/auth/oauth")
            return response
    except Exception:
        response = RedirectResponse(failure_url, status_code=302)
        response.delete_cookie(DASHBOARD_OAUTH_STATE_COOKIE, path="/my-dashboard/auth/oauth")
        response.delete_cookie(DASHBOARD_OAUTH_VERIFIER_COOKIE, path="/my-dashboard/auth/oauth")
        return response


@router.post("/my-dashboard/auth/oauth/exchange")
def my_dashboard_oauth_exchange(
    request: DashboardOAuthExchangeRequest,
    response: Response,
) -> Dict[str, Any]:
    now = _utcnow()
    Session = _session_factory()
    with Session() as session:
        login_code = (
            session.query(AppOAuthLoginCode)
            .filter(AppOAuthLoginCode.token_hash == _token_hash(request.code))
            .first()
        )
        if (
            login_code is None
            or login_code.used_at is not None
            or login_code.expires_at <= now
        ):
            raise HTTPException(status_code=400, detail="OAuth sign-in link is invalid or expired")
        db_session = session.query(AppSession).filter(AppSession.id == login_code.session_id).first()
        if db_session is None or db_session.expires_at <= now:
            raise HTTPException(status_code=400, detail="OAuth sign-in session is invalid or expired")
        user = session.query(AppUser).filter(AppUser.id == login_code.user_id).first()
        if user is None:
            raise HTTPException(status_code=400, detail="OAuth sign-in session is invalid or expired")
        _ensure_user_active(session, user)
        prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user.id).first()
        login_code.used_at = now
        db_session.last_seen_at = now
        access = access_payload_for_user(
            session,
            user,
            session_created_at=db_session.created_at,
        )
        response.set_cookie(
            key=DASHBOARD_SESSION_COOKIE,
            value=db_session.session_token,
            **_cookie_settings(),
        )
        session.commit()
        return {
            "ok": True,
            "user": _serialize_user(user, prefs, access),
            "session_token": db_session.session_token,
            "session_expires_at": db_session.expires_at.isoformat(),
        }


@router.post("/my-dashboard/auth/forgot-password")
def my_dashboard_forgot_password(
    request: DashboardForgotPasswordRequest,
) -> Dict[str, Any]:
    email = _normalize_email(request.email)
    if not email or "@" not in email:
        return {"ok": True, "message": DASHBOARD_PASSWORD_RESET_MESSAGE}

    Session = _session_factory()
    with Session() as session:
        user = session.query(AppUser).filter(AppUser.email == email).first()
        if user is None:
            return {"ok": True, "message": DASHBOARD_PASSWORD_RESET_MESSAGE}

        now = _utcnow()
        latest = (
            session.query(AppPasswordResetToken)
            .filter(AppPasswordResetToken.user_id == user.id)
            .order_by(AppPasswordResetToken.created_at.desc())
            .first()
        )
        if latest and latest.created_at > now - dt.timedelta(seconds=60):
            return {"ok": True, "message": DASHBOARD_PASSWORD_RESET_MESSAGE}

        token = secrets.token_urlsafe(32)
        (
            session.query(AppPasswordResetToken)
            .filter(
                AppPasswordResetToken.user_id == user.id,
                AppPasswordResetToken.used_at.is_(None),
            )
            .update({"used_at": now}, synchronize_session=False)
        )
        session.add(
            AppPasswordResetToken(
                user_id=user.id,
                token_hash=_token_hash(token),
                expires_at=now + dt.timedelta(minutes=DASHBOARD_PASSWORD_RESET_MINUTES),
                created_at=now,
            )
        )
        try:
            _send_password_reset_email(
                user.email,
                f"{_frontend_url()}?reset_token={quote(token)}",
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            print(f"[dashboard-auth] Password reset email could not be sent: {type(exc).__name__}")

    return {"ok": True, "message": DASHBOARD_PASSWORD_RESET_MESSAGE}


@router.post("/my-dashboard/auth/reset-password")
def my_dashboard_reset_password(
    request: DashboardResetPasswordRequest,
) -> Dict[str, Any]:
    now = _utcnow()
    Session = _session_factory()
    with Session() as session:
        reset = (
            session.query(AppPasswordResetToken)
            .filter(AppPasswordResetToken.token_hash == _token_hash(request.token))
            .first()
        )
        if reset is None or reset.used_at is not None or reset.expires_at <= now:
            raise HTTPException(status_code=400, detail="Password reset link is invalid or expired")
        user = session.query(AppUser).filter(AppUser.id == reset.user_id).first()
        if user is None:
            raise HTTPException(status_code=400, detail="Password reset link is invalid or expired")
        _ensure_user_active(session, user)
        user.password_hash = _hash_password(request.password)
        user.updated_at = now
        (
            session.query(AppPasswordResetToken)
            .filter(
                AppPasswordResetToken.user_id == user.id,
                AppPasswordResetToken.used_at.is_(None),
            )
            .update({"used_at": now}, synchronize_session=False)
        )
        session.query(AppSession).filter(AppSession.user_id == user.id).delete(
            synchronize_session=False
        )
        session.commit()
    return {"ok": True, "message": "Password updated. Sign in with your new password."}


@router.post("/my-dashboard/auth/logout")
def my_dashboard_logout(
    response: Response,
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    token = _resolve_session_token(mlb_dashboard_session, x_dashboard_session)
    Session = _session_factory()
    with Session() as session:
        if token:
            session.query(AppSession).filter(AppSession.session_token == token).delete(
                synchronize_session=False
            )
        session.commit()
    cookie = _cookie_settings()
    response.delete_cookie(
        key=DASHBOARD_SESSION_COOKIE,
        path=cookie["path"],
        secure=cookie["secure"],
        httponly=cookie["httponly"],
        samesite=cookie["samesite"],
    )
    return {"ok": True}


@router.post("/my-dashboard/profile")
def my_dashboard_profile_create(request: DashboardProfileRequest, response: Response) -> Dict[str, Any]:
    """Compatibility profile endpoint with safe register-or-login behavior."""

    email, username = _validated_identity(request.email, request.username)
    Session = _session_factory()
    with Session() as session:
        user = session.query(AppUser).filter(AppUser.email == email).first()
        if user is None:
            password = _validated_registration_password(request.password)
            user, prefs = _provision_new_user(
                session,
                email=email,
                username=username or "",
                password=password,
                preferences=request,
            )
            payload = _issue_dashboard_session(
                session,
                response,
                user,
                prefs,
                verified_login=False,
            )
        else:
            # Verify first. No profile or preference data is mutated on failure.
            user = _verified_login_user(session, email, request.password)
            now = _utcnow()
            user.username = username or user.username
            user.updated_at = now
            prefs = _upsert_preferences(session, user.id, request)
            payload = _issue_dashboard_session(
                session,
                response,
                user,
                prefs,
                verified_login=True,
            )
        session.commit()
        return payload


@router.get("/my-dashboard/profile")
def my_dashboard_profile_get(
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        principal = resolve_principal(
            session,
            _resolve_session_token(mlb_dashboard_session, x_dashboard_session),
        )
        if not principal:
            return {"authenticated": False}
        user = session.query(AppUser).filter(AppUser.id == principal.user_id).first()
        prefs = session.query(AppUserPreference).filter(AppUserPreference.user_id == user.id).first()
        session.commit()
        return {
            "authenticated": True,
            "user": _serialize_user(user, prefs, principal.access_payload()),
            "feature_choices": FEATURE_CHOICES,
        }


@router.get("/my-dashboard/workspace")
def my_dashboard_workspace(
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        principal = resolve_principal(
            session,
            _resolve_session_token(mlb_dashboard_session, x_dashboard_session),
        )
        if not principal:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        user = session.query(AppUser).filter(AppUser.id == principal.user_id).first()
        payload = _get_workspace_payload(session, user, principal.access_payload())
        session.commit()
        return payload


@router.post("/my-dashboard/folders/today/ensure")
def my_dashboard_ensure_today_folder(
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        folder = _get_or_create_today_folder(session, user.id)
        session.commit()
        return {
            "ok": True,
            "folder": _serialize_folder(folder, []),
        }


@router.post("/my-dashboard/folders")
def my_dashboard_create_folder(
    request: DashboardFolderCreateRequest,
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        now = _utcnow()
        folder_date = dt.date.fromisoformat(request.folder_date) if request.folder_date else None
        folder = AppDashboardFolder(
            user_id=user.id,
            folder_name=request.folder_name.strip(),
            folder_date=folder_date,
            is_default=bool(request.is_default),
            created_at=now,
            updated_at=now,
        )
        session.add(folder)
        session.commit()
        return {"ok": True, "folder": _serialize_folder(folder, [])}


@router.patch("/my-dashboard/folders/{folder_id}")
def my_dashboard_rename_folder(
    folder_id: int,
    request: DashboardFolderRenameRequest,
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        folder = (
            session.query(AppDashboardFolder)
            .filter(AppDashboardFolder.id == folder_id, AppDashboardFolder.user_id == user.id)
            .first()
        )
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        folder.folder_name = _validated_dashboard_name(request.folder_name)
        folder.updated_at = _utcnow()
        session.commit()
        return {"ok": True, "folder": _serialize_folder(folder, [])}


@router.get("/my-dashboard/items")
def my_dashboard_items(
    folder_id: Optional[int] = Query(default=None),
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        query = session.query(AppDashboardItem).filter(AppDashboardItem.user_id == user.id)
        if folder_id is not None:
            query = query.filter(AppDashboardItem.folder_id == folder_id)
        items = query.order_by(AppDashboardItem.pin_order.asc().nullslast(), AppDashboardItem.id.asc()).all()
        session.commit()
        return {"items": [_serialize_item(item) for item in items]}


@router.post("/my-dashboard/items")
def my_dashboard_create_item(
    request: DashboardItemCreateRequest,
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        folder = session.query(AppDashboardFolder).filter(AppDashboardFolder.id == request.folder_id, AppDashboardFolder.user_id == user.id).first()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        now = _utcnow()
        item = AppDashboardItem(
            user_id=user.id,
            folder_id=folder.id,
            source_tab=request.source_tab,
            source_type=request.source_type,
            title=_validated_dashboard_name(request.title),
            subtitle=request.subtitle,
            payload_json=request.payload_json,
            filter_json=request.filter_json,
            sort_json=request.sort_json,
            pin_order=request.pin_order,
            notes=request.notes,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        session.commit()
        return {"ok": True, "item": _serialize_item(item)}


@router.patch("/my-dashboard/items/{item_id}")
def my_dashboard_rename_item(
    item_id: int,
    request: DashboardItemRenameRequest,
    mlb_dashboard_session: Optional[str] = Cookie(default=None),
    x_dashboard_session: Optional[str] = Header(default=None, alias="X-Dashboard-Session"),
) -> Dict[str, Any]:
    Session = _session_factory()
    with Session() as session:
        user = _get_active_user(session, _resolve_session_token(mlb_dashboard_session, x_dashboard_session))
        if not user:
            raise HTTPException(status_code=401, detail="Dashboard sign-in required")
        item = (
            session.query(AppDashboardItem)
            .filter(AppDashboardItem.id == item_id, AppDashboardItem.user_id == user.id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Saved report not found")
        item.title = _validated_dashboard_name(request.title)
        item.updated_at = _utcnow()
        session.commit()
        return {"ok": True, "item": _serialize_item(item)}
