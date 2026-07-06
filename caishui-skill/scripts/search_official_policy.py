#!/usr/bin/env python3
"""检索中国大陆财税官方政策来源。

脚本不依赖第三方库，当前检索：
- 中国政府网：国务院和部委文件。
- 国家税务总局站内搜索。

检索结果只能作为证据候选。正式用于申报或答复前，仍要打开官方页面核对正文、施行日期、废止状态和适用地区。
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Optional


GOV_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCSMhMJQ+XLI7oW0k9Bwufur4Ag40tcsrzT7WZf6Ao0O/hyY1gZtCSYFxkxIZUXjW46j27XSW8IDX1rTJoHaMxHCWsOpTi2W5stybGYZytsY5on8gd8AIaS1d52h9eaS2TFydtJJtE50xHmT0WmoyoinWCuVCOkdCLhh9b9jSdeSQIDAQAB
-----END PUBLIC KEY-----"""

GOV_APP_TOKEN = b"a46884b2013e4d189f2a8e2d49a23525"
GOV_SEARCH_URL = (
    "https://sousuoht.www.gov.cn/athena/forward/"
    "2B22E8E39E850E17F95A016A74FCB6B673336FA8B6FEC0E2955907EF9AEE06BE"
)
CHINATAX_SEARCH_URL = "https://www.chinatax.gov.cn/search5/search/s"


@dataclass
class SearchResult:
    source: str
    title: str
    url: str
    published_at: str = ""
    authority: str = ""
    document_no: str = ""
    category: str = ""
    snippet: str = ""


def strip_html(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def http_json(
    url: str,
    *,
    data: Optional[bytes] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 20,
) -> Any:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    return json.loads(raw)


def read_len(buf: bytes, offset: int) -> tuple[int, int]:
    first = buf[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    length = int.from_bytes(buf[offset : offset + count], "big")
    return length, offset + count


def read_tlv(buf: bytes, offset: int) -> tuple[int, bytes, int]:
    tag = buf[offset]
    length, start = read_len(buf, offset + 1)
    end = start + length
    return tag, buf[start:end], end


def rsa_public_numbers_from_pem(pem: str) -> tuple[int, int]:
    body = "".join(line for line in pem.splitlines() if "-----" not in line)
    der = base64.b64decode(body)
    tag, spki, _ = read_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("expected SubjectPublicKeyInfo sequence")
    _, _, offset = read_tlv(spki, 0)  # algorithm identifier
    bit_tag, bit_string, _ = read_tlv(spki, offset)
    if bit_tag != 0x03 or not bit_string or bit_string[0] != 0:
        raise ValueError("expected RSA public key bit string")
    tag, rsa_seq, _ = read_tlv(bit_string[1:], 0)
    if tag != 0x30:
        raise ValueError("expected RSAPublicKey sequence")
    mod_tag, mod_bytes, offset = read_tlv(rsa_seq, 0)
    exp_tag, exp_bytes, _ = read_tlv(rsa_seq, offset)
    if mod_tag != 0x02 or exp_tag != 0x02:
        raise ValueError("expected RSA integer fields")
    return int.from_bytes(mod_bytes.lstrip(b"\x00"), "big"), int.from_bytes(exp_bytes, "big")


def rsa_pkcs1_v15_encrypt(message: bytes, pem: str) -> str:
    modulus, exponent = rsa_public_numbers_from_pem(pem)
    key_len = (modulus.bit_length() + 7) // 8
    if len(message) > key_len - 11:
        raise ValueError("message too long for RSA key")
    padding_len = key_len - len(message) - 3
    padding = bytearray()
    while len(padding) < padding_len:
        chunk = secrets.token_bytes(padding_len - len(padding))
        padding.extend(b for b in chunk if b != 0)
    encoded = b"\x00\x02" + bytes(padding[:padding_len]) + b"\x00" + message
    cipher = pow(int.from_bytes(encoded, "big"), exponent, modulus)
    return base64.b64encode(cipher.to_bytes(key_len, "big")).decode("ascii")


def search_gov(query: str, limit: int, order_by: str) -> list[SearchResult]:
    app_key = urllib.parse.quote(rsa_pkcs1_v15_encrypt(GOV_APP_TOKEN, GOV_PUBLIC_KEY_PEM))
    payload = {
        "code": "17da70961a7",
        "searchWord": query,
        "dataTypeId": "107",
        "orderBy": order_by,
        "searchBy": "all",
        "appendixType": "",
        "granularity": "ALL",
        "trackTotalHits": True,
        "beginDateTime": "",
        "endDateTime": "",
        "isSearchForced": 0,
        "filters": [],
        "pageNo": 1,
        "pageSize": limit,
        "customFilter": {"operator": "and", "properties": []},
    }
    data = http_json(
        GOV_SEARCH_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json;charset=utf-8",
            "athenaAppName": urllib.parse.quote("国网搜索"),
            "athenaAppKey": app_key,
            "User-Agent": "Mozilla/5.0",
        },
    )
    items = data.get("result", {}).get("data", {}).get("middle", {}).get("list", [])
    results: list[SearchResult] = []
    for item in items[:limit]:
        results.append(
            SearchResult(
                source="gov.cn",
                title=strip_html(item.get("title_no_tag") or item.get("title")),
                url=item.get("url", ""),
                published_at=item.get("time", ""),
                authority=strip_html(item.get("agencies") or item.get("source")),
                document_no=strip_html(item.get("pubcode")),
                category=strip_html(item.get("label") or item.get("type")),
                snippet=strip_html(item.get("summary") or item.get("content"))[:500],
            )
        )
    return results


def search_chinatax(query: str, limit: int, site_code: str) -> list[SearchResult]:
    form = urllib.parse.urlencode(
        {
            "siteCode": site_code,
            "searchWord": query,
            "column": "全部",
            "uc": "1",
            "left_right_index": "0",
        }
    ).encode("utf-8")
    data = http_json(
        CHINATAX_SEARCH_URL,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.chinatax.gov.cn/search5/html/searchResult.html",
        },
    )
    items = data.get("searchResultAll", {}).get("searchTotal", [])
    results: list[SearchResult] = []
    for item in items[:limit]:
        results.append(
            SearchResult(
                source="chinatax.gov.cn",
                title=strip_html(item.get("title") or item.get("zwtitle")),
                url=item.get("url") or item.get("snapshotUrl") or "",
                published_at=item.get("pubDate", ""),
                authority=strip_html(item.get("pubName") or item.get("source") or item.get("siteName")),
                document_no=strip_html((item.get("govDoc") or {}).get("docNo", "")),
                category=strip_html(item.get("column") or item.get("label")),
                snippet=strip_html(item.get("shortContent") or item.get("content"))[:500],
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="检索中国政府网和国家税务总局的官方财税政策来源。")
    parser.add_argument("query", help="政策关键词。")
    parser.add_argument("--source", choices=["all", "gov", "chinatax"], default="all")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--order-by", choices=["related", "time"], default="related")
    parser.add_argument("--site-code", default="bm29000002", help="国家税务总局站内搜索 siteCode，默认总局。")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果。")
    args = parser.parse_args()

    results: list[SearchResult] = []
    errors: list[dict[str, str]] = []

    if args.source in ("all", "gov"):
        try:
            results.extend(search_gov(args.query, args.limit, args.order_by))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"source": "gov.cn", "error": str(exc)})

    if args.source in ("all", "chinatax"):
        try:
            results.extend(search_chinatax(args.query, args.limit, args.site_code))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"source": "chinatax.gov.cn", "error": str(exc)})

    payload = {"query": args.query, "results": [asdict(r) for r in results], "errors": errors}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for index, result in enumerate(results, 1):
            print(f"{index}. [{result.source}] {result.title}")
            print(f"   日期: {result.published_at} 发布机关: {result.authority}")
            if result.document_no:
                print(f"   文号: {result.document_no}")
            print(f"   链接: {result.url}")
            if result.snippet:
                print(f"   摘要: {result.snippet}")
        if errors:
            print("\n检索错误:", file=sys.stderr)
            for error in errors:
                print(f"- {error['source']}: {error['error']}", file=sys.stderr)
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
