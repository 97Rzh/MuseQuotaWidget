"""共用的网页登录换令牌逻辑：可见登录窗和后台登录窗都用它，
保证两路行为一致。浏览器数据文件夹是同一个，Cookie 共享，
所以后台能用可见窗留下的登录 Cookie 静默换令牌。

在浏览器里同源执行一次 POST /api/auth/check（ai-quota 的做法），
只取 outcome / access_token / viewer_id / session_binding_id /
type / reason / status 这几个字段，不取 Cookie，不把令牌发给别处。
返回 None 表示本次未拿到新令牌，调用方按指纹决定是否复用旧令牌。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import diagnostics
from .quota_api import MuseAuthException, MuseAuthKind, MuseCredential

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
    if (json && typeof json === 'object') {
      for (const key of ['outcome', 'access_token', 'viewer_id', 'session_binding_id', 'type', 'reason', 'status']) {
        if (Object.prototype.hasOwnProperty.call(json, key)) payload[key] = json[key];
      }
    }
    window.__museQuotaAuthResult = JSON.stringify({ httpStatus: response.status, payload: payload });
  }).catch((e) => {
    window.__museQuotaAuthResult = JSON.stringify({ httpStatus: 0, payload: { type: 'fetchFailed', reason: e && e.name ? e.name : 'unknown' } });
  });
  return 'started';
})()
"""

POLL_JS = "window.__museQuotaAuthResult"


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
    diagnostics.log(
        f"auth: httpStatus={status} payload=[{diagnostics.describe_keys(payload)}] "
        f"outcome={get_str('outcome') or '(none)'} type={get_str('type') or '(none)'} "
        f"reason={get_str('reason') or '(none)'} hasToken={bool(get_str('access_token'))} "
        f"bindingKind={binding_kind}"
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
    if token:
        return MuseCredential(token=token, fingerprint=fingerprint)

    # 本次没给新令牌：只有指纹与旧凭据完全一致时才复用旧令牌。
    if old_credential is not None and old_credential.fingerprint == fingerprint:
        return None

    raise MuseAuthException(MuseAuthKind.TOKEN_UNAVAILABLE)
