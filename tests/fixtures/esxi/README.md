# tests/fixtures/esxi/ — vSphere Web Services API(/sdk) SOAP fixture

Phase 4-B(2026-08-10)에서 ESXi Protocol Detection 을 `/sdk` HTTP status 기반에서
**실제 vim25 SOAP 응답 확인**으로 바꾸면서 추가했다. `common/library/precheck_bundle.py`
의 `parse_service_content()` 회귀 고정용이다.

## 출처 (rule 21 R2)

**저장소에 `/sdk` wire capture 는 없다.** 아래 두 종류를 구분해서 쓴다.

| 디렉터리 | 값의 출처 | 신뢰 수준 |
|---|---|---|
| `lab/` | ESXi **실장비 3대**(2026-04-28 수집)의 AboutInfo 실측값 | 값은 실측, 봉투는 라이브러리 생성 |
| `synthetic/` | 값까지 합성 | 구조 회귀 전용 — **"해당 버전 검증 완료" 아님** |

### `lab/esxi_7_0_3_service_content.xml`

- AboutInfo 값 출처: `tests/reference/esxi/{10_100_64_1,10_100_64_2,10_100_64_3}/pyvmomi_host_dump.json`
  의 `config_product` (세 대 모두 동일한 값이라 하나로 합쳤다).
  - `VMware ESXi 7.0.3 build-20842708` / `apiType=HostAgent` / `apiVersion=7.0.3.0`
    / `productLineId=embeddedEsx`
  - `config_product` 는 `vim.HostSystem.config.product` 이며 타입이
    `ServiceContent.about` 과 같은 `vim.AboutInfo` 다.
- SOAP 봉투/직렬화: 설치본 **pyVmomi 9.x** 의 `SoapAdapter.SerializeToStr` 로 생성
  (손으로 쓴 XML 이 아니다). 생성 후 pyVmomi `SoapResponseDeserializer` 로 되읽어
  `vim.ServiceInstanceContent` 로 복원되는 것까지 확인했다.
- **한계**: hostd 가 실제 wire 로 내보낸 바이트가 아니다. 사이트/lab 에서 `/sdk` 응답을
  캡처하면 이 파일을 교체하고 본 문서를 갱신한다.

### `synthetic/*`

| 파일 | 내용 | 근거 |
|---|---|---|
| `esxi_6_0_0_service_content.xml` | ESXi 6.0 AboutInfo (합성) | 버전 독립성 회귀. 저장소 지원 하한(`adapters/esxi/esxi_6x.yml`) |
| `esxi_6_7_0_service_content.xml` | ESXi 6.7 AboutInfo (합성) | 〃 |
| `esxi_8_0_3_service_content.xml` | ESXi 8.0 AboutInfo (합성) | 〃 |
| `vcenter_8_0_3_service_content.xml` | `apiType=VirtualCenter` (합성) | ServiceInstance 는 vCenter 에도 있다는 사실 고정(§10) |
| `vsphere_fault_vim25.xml` | `InvalidRequestFault xmlns="urn:vim25"` | hostd Fault 형태 — VMware Technology Network / Broadcom community 사례(확인 2026-08-10) |
| `vsphere_fault_internalvim25.xml` | `ManagedObjectNotFoundFault xmlns="urn:internalvim25"` | 〃 |
| `generic_soap_fault_NEGATIVE.xml` | vSphere 네임스페이스가 없는 일반 SOAP Fault | **거부되어야 하는** 음성 표본 |

## 재생성

`lab/` 과 `synthetic/` 의 ServiceContent 는 pyVmomi 로 재생성할 수 있다.

```python
from pyVmomi import SoapAdapter, VmomiSupport, vim, vmodl

about = vim.AboutInfo(**about_kwargs)          # lab 은 config_product 값 그대로
sc = vim.ServiceInstanceContent(
    rootFolder=vim.Folder("ha-folder-root"),
    propertyCollector=vmodl.query.PropertyCollector("ha-property-collector"),
    about=about,
    sessionManager=vim.SessionManager("ha-sessionmgr"))
info = VmomiSupport.Object(name="returnval", type=vim.ServiceInstanceContent,
                           version="vim.version.version10", flags=0)
body = SoapAdapter.SerializeToStr(sc, info=info, version="vim.version.version10")
# → <RetrieveServiceContentResponse xmlns="urn:vim25">{body}</...> 를 SOAP 1.1 봉투로 감싼다
```

## 주의

- 자격증명 / 세션 쿠키 / Authorization 헤더는 어떤 파일에도 들어 있지 않다.
  Protocol Probe 자체가 비인증 요청이다.
- 호스트 주소는 문서용 주소(RFC 5737 `192.0.2.0/24`)만 쓴다. lab IP 는 fixture 에 없다.
