"""共用的网页登录换令牌逻辑：可见登录窗和后台登录窗都用它，
保证两路行为一致。浏览器数据文件夹是同一个，Cookie 共享，
所以后台能用可见窗留下的登录 Cookie 静默换令牌。

在浏览器里同源执行一次 POST /api/auth/check（ai-quota 的做法），
只取 outcome / access_token / viewer_id / session_binding_id /
type / reason / status 以及账号展示字段（email/username/display_name/
name/phone 和嵌套 user/account/profile），不取 Cookie，
不把令牌发给别处。账号值只存内存、不进日志。
返回 None 表示本次未拿到新令牌，调用方按指纹决定是否复用旧令牌。
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from . import diagnostics
from .quota_api import MuseAuthException, MuseAuthKind, MuseCredential, extract_account

AUTH_JS = """
(() => {
  window.__museQuotaAuthResult = null;
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 10000);
  fetch('/api/auth/check', {
    method: 'POST', credentials: 'include', cache: 'no-store', signal: controller.signal
  }).then(async (response) => {
    let json = null;
    try { json = await response.json(); } catch (e) { json = null; }
    const payload = {};
    // 账号字段定位用：除了上面白名单的值，还把全部字段名（仅键名，
    // 不含任何值）和嵌套 user/account/profile/viewer 的字段名一起上报，
    // 这样响应里即使有个我们没列出的账号键，也能在日志里看到它的名字，
    // 下一版按那个真实键名取，不用再猜。
    const allKeys = (json && typeof json === 'object') ? Object.keys(json) : [];
    const nestedKeys = {};
    for (const ck of ['user', 'account', 'profile', 'viewer']) {
      if (json && json[ck] && typeof json[ck] === 'object' && !Array.isArray(json[ck])) nestedKeys[ck] = Object.keys(json[ck]);
    }
    if (json && typeof json === 'object') {
      for (const key of ['outcome', 'access_token', 'viewer_id', 'session_binding_id', 'type', 'reason', 'status', 'email', 'user_email', 'account_email', 'email_address', 'emailAddress', 'username', 'user_name', 'userName', 'display_name', 'displayName', 'full_name', 'fullName', 'name', 'nickname', 'phone', 'phone_number', 'phoneNumber', 'user', 'account', 'profile']) {
        if (Object.prototype.hasOwnProperty.call(json, key)) payload[key] = json[key];
      }
    }
    window.__museQuotaAuthResult = JSON.stringify({ httpStatus: response.status, payload: payload, allKeys: allKeys, nestedKeys: nestedKeys });
  }).catch((e) => {
    window.__museQuotaAuthResult = JSON.stringify({ httpStatus: 0, payload: { type: 'fetchFailed', reason: e && e.name ? e.name : 'unknown' } });
  });
  return 'started';
})()
"""

POLL_JS = "window.__museQuotaAuthResult"


def _jwt_account(token: str) -> Optional[str]:
    """令牌若是 JWT，试着从 payload 里取账号展示名（内存里解，不记值）。

    不是 JWT（没有三个点分段、payload 不是 JSON）时直接返回 None，
    不报错、不影响原流程。只认 email / preferred_username / name，
    sub / user_id 这类内部 id 不算账号。
    """
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("email", "preferred_username", "username", "display_name", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and len(value.strip()) <= 100:
            return value.strip()
    return None


def _json_kind(value: Any) -> str:
    if value is None:
        return "Null"
    if isinstance(value, bool):
        return "True/False"
    if isinstance(value, (int, float)):
        return "Number"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list):
        return "Array"
    if isinstance(value, dict):
        return "Object"
    return type(value).__name__


def process_auth_result(
    json_text: str, old_credential: Optional[MuseCredential]
) -> Optional[MuseCredential]:
    """处理浏览器里 fetch 回来的 JSON 字符串。

    返回新凭据，或 None（本次没给新令牌但指纹与旧凭据一致，复用旧令牌），
    其余情况按 C# 版的规则抛 MuseAuthException。
    只记结构不记值：状态码、字段名、outcome/type/reason、
    有无令牌（布尔值）、binding 的类型，令牌与账号 id 一律不记。
    """
    try:
        root = json.loads(json_text)
    except json.JSONDecodeError:
        diagnostics.log(f"auth invalid: script result keys=[(not json)]")
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)
    if not isinstance(root, dict):
        diagnostics.log(f"auth invalid: script result keys=[(not object)]")
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    status = root.get("httpStatus")
    payload = root.get("payload")
    if not isinstance(status, int) or not isinstance(payload, dict):
        diagnostics.log(f"auth invalid: script result keys=[{diagnostics.describe_keys(root)}]")
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    def get_str(name: str) -> Optional[str]:
        value = payload.get(name)
        return value if isinstance(value, str) else None

    binding = payload.get("session_binding_id")
    binding_kind = _json_kind(binding)
    # 账号字段定位用：只记取到了哪个键（或 none），不记账号值本身。
    _account_preview = extract_account(payload)
    _account_field = "none"
    if _account_preview is not None:
        for _key in ("email", "user_email", "account_email", "username", "user_name", "display_name", "name", "phone"):
            if isinstance(payload.get(_key), str) and payload.get(_key, "").strip() == _account_preview:
                _account_field = _key
                break
        else:
            _account_field = "nested-or-jwt"
    _all_keys = root.get("allKeys")
    _all_keys_text = ",".join(_all_keys) if isinstance(_all_keys, list) and all(isinstance(k, str) for k in _all_keys) else "(none)"
    _nested = root.get("nestedKeys")
    _nested_text = ""
    if isinstance(_nested, dict):
        _nested_text = " nestedKeys={" + ", ".join(f"{k}:[{','.join(v)}]" for k, v in _nested.items() if isinstance(v, list)) + "}"
    diagnostics.log(
        f"auth: httpStatus={status} payload=[{diagnostics.describe_keys(payload)}] "
        f"outcome={get_str('outcome') or '(none)'} type={get_str('type') or '(none)'} "
        f"reason={get_str('reason') or '(none)'} hasToken={bool(get_str('access_token'))} "
        f"bindingKind={binding_kind} accountField={_account_field} allKeys=[{_all_keys_text}]{_nested_text}"
    )

    if status == 401:
        raise MuseAuthException(MuseAuthKind.LOGIN_REQUIRED, 401)
    if status == 403 and get_str("type") == "checkpointRequired":
        raise MuseAuthException(MuseAuthKind.CHECKPOINT_REQUIRED, 403)
    if status == 403 and get_str("type") == "hatchAdmissionInvalidated" and get_str("reason") in ("entitlement", "activation"):
        raise MuseAuthException(MuseAuthKind.ACCESS_RESTRICTED, 403)
    if status < 200 or status >= 300:
        raise MuseAuthException(MuseAuthKind.REQUEST_REJECTED, status)
    if get_str("outcome") != "validated":
        raise MuseAuthException(MuseAuthKind.LOGIN_REQUIRED)

    viewer_id = get_str("viewer_id")
    if not viewer_id:
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    binding_str: Optional[str] = None
    if isinstance(binding, str):
        binding_str = binding
    elif binding is not None:
        raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

    fingerprint = MuseCredential.fingerprint_for(viewer_id, binding_str)
    token = get_str("access_token")
    # 账号展示名来源（按优先级，内存里取，不记值）：
    # ① auth/check 响应里的邮箱/用户名/姓名字段；② 令牌是 JWT 时的
    # payload 里的 email/name；③ 都没有就是 None，界面不得用“已登录”冒充。
    account = extract_account(payload)
    if account is None and token:
        account = _jwt_account(token)
    if token:
        return MuseCredential(token=token, fingerprint=fingerprint, account=account)

    # 本次没给新令牌：只有指纹与旧凭据完全一致时才复用旧令牌。
    if old_credential is not None and old_credential.fingerprint == fingerprint:
        # 复用时若这次拿到了旧凭据没有的账号名，把账号补上去，
        # 否则返回 None 让调用方继续用旧凭据（账号也还是旧的）。
        if account is not None and old_credential.account != account:
            return MuseCredential(token=old_credential.token, fingerprint=fingerprint, account=account)
        return None

    raise MuseAuthException(MuseAuthKind.TOKEN_UNAVAILABLE)
