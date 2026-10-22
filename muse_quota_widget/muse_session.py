"""内存里的 Muse 会话：只存令牌与指纹，不存盘。

额度读取流程参照 ai-quota 的 MuseQuotaProvider：
GET https://hatch-api.meta.ai/hatch/subscription，
Authorization: Bearer 令牌，X-API-Version: 1.0.0，Accept: application/json，
不带 Cookie，超时 10 秒；不请求 include=agreement（不碰支付与协议详情）。
读取前后核对指纹，指纹变了就视为换号并丢弃令牌。
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional

from .quota_api import (
    MuseAuthException,
    MuseAuthKind,
    MuseCredential,
    QuotaData,
    log_quota_numbers,
    log_quota_shape,
    parse_quota,
)

SUBSCRIPTION_URL = "https://hatch-api.meta.ai/hatch/subscription"


class MuseSession:
    def __init__(self) -> None:
        self.credential: Optional[MuseCredential] = None

    @property
    def has_token(self) -> bool:
        return self.credential is not None and bool(self.credential.token.strip())

    def set_credential(self, credential: MuseCredential) -> None:
        self.credential = credential

    def clear(self) -> None:
        self.credential = None

    def fetch_quota(self) -> QuotaData:
        credential = self.credential
        if credential is None or not credential.token.strip():
            raise MuseAuthException(MuseAuthKind.LOGIN_REQUIRED)

        request = urllib.request.Request(
            SUBSCRIPTION_URL,
            method="GET",
            headers={
                "Authorization": f"Bearer {credential.token}",
                "X-API-Version": "1.0.0",
                "Accept": "application/json",
            },
        )
        # 不用带 Cookie 的 opener：urllib 默认的 build_opener 不含
        # HTTPCookieProcessor 就不会存取 Cookie，与 C# 的 UseCookies=false 对应。
        opener = urllib.request.build_opener()
        try:
            with opener.open(request, timeout=10) as response:
                status = response.status
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            # HTTPError 也要走下面的状态分流，不能直接按网络失败算。
            return self._handle_status(status, body, credential)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise MuseAuthException(MuseAuthKind.NETWORK_UNAVAILABLE)

        return self._handle_status(status, body, credential)

    def _handle_status(self, status: int, body: str, credential: MuseCredential) -> QuotaData:
        # 读取后核对身份：会话在读取期间被换掉（例如点了退出登录），
        # 这次结果就不能算当前账号的，丢弃并按换号处理。
        current = self.credential
        if current is None or current.fingerprint != credential.fingerprint:
            self.clear()
            raise MuseAuthException(MuseAuthKind.ACCOUNT_CHANGED)

        if status == 401:
            self.clear()
            raise MuseAuthException(MuseAuthKind.LOGIN_REQUIRED, 401)
        if status == 429:
            raise MuseAuthException(MuseAuthKind.RATE_LIMITED, 429)
        if not (200 <= status < 300):
            raise MuseAuthException(MuseAuthKind.REQUEST_REJECTED, status)
        if not body.strip() or len(body) > 1_048_576:
            raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)

        try:
            data = parse_quota(body)
            # 每次成功也记一行数值字段（只记额度数值，不记凭据），
            # 用于对额外 token 的数；日志会随刷新增长，可随时删除。
            log_quota_numbers(body)
            return data
        except MuseAuthException:
            log_quota_shape(body)
            raise
        except Exception:
            log_quota_shape(body)
            raise MuseAuthException(MuseAuthKind.INVALID_RESPONSE)
