"""Jenkins 접근 (curl) — 세션 crumb · 쿠키, 읽기, 투입, 대기, 중단, artifact 저장 (2026-11-09).

- crumb 은 웹 세션에 묶인다 — crumb 을 받은 쿠키 jar 로 POST 해야 한다(jar 는 작업 폴더, 끝나면 drop()).
- 자격은 netrc 파일 경로로만 curl 에 넘긴다. 이 모듈은 그 파일을 열지 않는다.
- TLS 는 고정한 Jenkins 인증서(`--cacert`)로만 검증한다. `-k`(검증 끔)는 쓰지 않는다 — 자격을 실어 보내기 때문이다.
  인증서는 `python -m scripts.ai.longrun pin-cert` 가 지문을 대조한 뒤에만 저장한다(rule 80 R8).
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

# curl 이 TLS 검증 단계에서 멈췄을 때의 종료 코드 (curl 문서: 35 연결 · 51 · 60 인증서 · 77 CA 파일 · 58 · 83 · 90 · 91)
TLS_FAIL_RC = {35, 51, 58, 60, 77, 83, 90, 91}


class JenkinsError(RuntimeError):
    pass


class Jenkins:
    def __init__(self, url: str, netrc: Path, jar: Path | None = None, *, cacert: Path, curl: str = "curl"):
        self.url = url.rstrip("/")
        self.netrc = str(netrc)
        self.jar = jar
        self.cacert = Path(cacert)
        self.curl_bin = curl
        self.crumb_header: str | None = None
        self.last_rc = 0

    # ------------------------------------------------------------------ 기본
    def job_url(self, job: str) -> str:
        return self.url + "".join(f"/job/{p}" for p in job.split("/"))

    def _base(self, timeout: int) -> list[str]:
        return [self.curl_bin, "-sg", "--cacert", str(self.cacert), "--netrc-file", self.netrc, "--max-time", str(timeout)]

    def request(self, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
        """(http_code, body, headers)."""
        jar = ["-c", str(self.jar), "-b", str(self.jar)] if self.jar else []
        post = ["-H", self.crumb_header] if (self.crumb_header and "POST" in args) else []
        cmd = [*self._base(timeout), "-D", "-", "-w", "\n%{http_code}", *jar, *post, *args]
        p = subprocess.run(cmd, capture_output=True)
        self.last_rc = p.returncode
        out = p.stdout.decode("utf-8", "replace")
        body, _, code = out.rpartition("\n")
        hdr_end = body.find("\r\n\r\n")
        headers, payload = (body[:hdr_end], body[hdr_end + 4:]) if hdr_end >= 0 else ("", body)
        try:
            return int(code.strip()), payload, headers
        except ValueError:
            return 0, payload, headers

    def get_json(self, url: str, timeout: int = 120):
        code, body, _ = self.request([url], timeout)
        if code != 200:
            hint = (" - TLS 검증 실패: 고정한 인증서와 서버 인증서가 다르거나 인증서 파일이 없다. 지문을 사용자와 확인한 뒤 pin-cert 로 다시 받는다"
                    if code == 0 and self.last_rc in TLS_FAIL_RC else "")
            raise JenkinsError(f"GET {url} -> HTTP {code} (curl rc {self.last_rc}){hint}")
        return json.loads(body)

    def download(self, url: str, out: Path, timeout: int = 300) -> int:
        """바이트 그대로 저장(증거 파일의 digest 를 바꾸지 않는다). HTTP 코드를 돌려준다."""
        p = subprocess.run([*self._base(timeout), "-o", str(out), "-w", "%{http_code}", url], capture_output=True)
        self.last_rc = p.returncode
        try:
            return int(p.stdout.decode("ascii", "replace").strip()[-3:])
        except ValueError:
            return 0

    def login(self) -> None:
        cr = self.get_json(f"{self.url}/crumbIssuer/api/json")
        self.crumb_header = f"{cr['crumbRequestField']}: {cr['crumb']}"

    def drop(self) -> None:
        if self.jar and Path(self.jar).exists():
            Path(self.jar).unlink()
        self.crumb_header = None

    # ------------------------------------------------------------------ 빌드
    def params(self, job: str, build: int) -> dict:
        d = self.get_json(f"{self.job_url(job)}/{build}/api/json?tree=actions[parameters[name,value]]")
        return params_of(d)

    def trigger(self, job: str, params: dict) -> str:
        args = ["-X", "POST", "-H", "Expect:", f"{self.job_url(job)}/buildWithParameters"]
        for k, v in params.items():
            args += ["--data-urlencode", f"{k}={'' if v is None else v}"]
        code, body, headers = self.request(args)
        if code not in (200, 201):
            raise JenkinsError(f"trigger -> HTTP {code}: {body[:200]}")
        m = re.search(r"^Location:\s*(\S+)", headers + "\n" + body, re.M | re.I)
        if not m:
            raise JenkinsError("trigger: queue Location 헤더 없음")
        return m.group(1).rstrip("/")

    def wait_build_number(self, queue_url: str, limit_s: int = 600) -> int:
        t0 = time.time()
        while time.time() - t0 < limit_s:
            q = self.get_json(f"{queue_url}/api/json")
            ex = q.get("executable")
            if ex and ex.get("number"):
                return int(ex["number"])
            if q.get("cancelled"):
                raise JenkinsError("queue item cancelled")
            time.sleep(3)
        raise JenkinsError("queue wait timeout")

    def build_info(self, job: str, build: int) -> dict:
        return self.get_json(f"{self.job_url(job)}/{build}/api/json?tree=number,result,building,duration,timestamp,"
                             "actions[lastBuiltRevision[SHA1]]")

    def wait_done(self, job: str, build: int, limit_s: int = 3 * 3600, poll_s: float = 10) -> dict:
        t0 = time.time()
        while time.time() - t0 < limit_s:
            b = self.build_info(job, build)
            if not b.get("building") and b.get("result"):
                return b
            time.sleep(poll_s)
        raise JenkinsError("build wait timeout")

    def console_has(self, job: str, build: int, marker: str) -> bool:
        code, body, _ = self.request([f"{self.job_url(job)}/{build}/consoleText"], timeout=60)
        return code == 200 and marker in body

    def stop(self, job: str, build: int) -> int:
        code, _, _ = self.request(["-X", "POST", f"{self.job_url(job)}/{build}/stop"])
        return code

    def artifact_text(self, job: str, build: int, rel: str) -> tuple[int, str]:
        code, body, _ = self.request([f"{self.job_url(job)}/{build}/artifact/{rel}"])
        return code, body


def params_of(build_json: dict) -> dict:
    return {p["name"]: p.get("value") for a in build_json.get("actions", []) if a and "parameters" in a for p in a["parameters"]}


# ---------------------------------------------------------------------- 인증서 고정
def fingerprint(pem: str) -> str:
    """openssl `x509 -fingerprint -sha256` 과 같은 표기 (DER 의 SHA-256, 대문자 · 콜론)."""
    h = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _norm_fp(fp: str) -> str:
    return re.sub(r"[^0-9A-F]", "", fp.upper())


def pin_cert(url: str, out: Path, expect_sha256: str | None, *, fetch=ssl.get_server_certificate, timeout: float = 20.0) -> tuple[int, str]:
    """서버가 보여 주는 인증서를 받아 지문을 대조하고, 같을 때만 `out` 에 쓴다. (rc, 지문).

    rc 0 저장 · 2 기대 지문 없음(출력만 — 사용자와 확인한 뒤 --expect-sha256 으로 다시) · 4 지문 다름(저장하지 않는다).
    받는 연결은 검증 없이 열리지만(처음 받는 것이므로), 저장 여부는 지문 대조가 정한다.
    """
    u = urlsplit(url)
    pem = fetch((u.hostname, u.port or 443), timeout=timeout)
    fp = fingerprint(pem)
    if not expect_sha256:
        return 2, fp
    if _norm_fp(fp) != _norm_fp(expect_sha256):
        return 4, fp
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pem, encoding="ascii")
    return 0, fp


def checkout_sha(build_json: dict) -> str | None:
    return next((x["lastBuiltRevision"]["SHA1"] for x in build_json.get("actions", []) if x and "lastBuiltRevision" in x), None)
