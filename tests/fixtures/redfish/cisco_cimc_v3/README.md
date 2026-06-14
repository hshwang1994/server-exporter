# Cisco CIMC 3.x (UCS C-series M5) fixture — M-H4 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Priority 1 fixture.

## 출처

- Sources: `https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/c/sw/api/3_0/b_Cisco_IMC_REST_API_guide_301/m_redfish_api_examples.html`
- Generation: CIMC 3.x (UCS C-series M5 — Skylake-SP) 2017-2020

## 시뮬레이션 시나리오 (실제 fixture 기준)

- ServiceRoot.RedfishVersion: "1.6.0" (DSP0268 v1.6+)
- Manufacturer: "Cisco Systems Inc."
- Model: "UCSC-C220-M5SX", BiosVersion: "C220M5.4.1.2c.0...", HostName: "cisco-c220-m5"
- Standard storage path
- OEM strategy: standard_only (Cisco OEM tasks 디렉터리 미생성)

## 매칭 검증

- 실제 fixture (C220-M5 / BIOS 4.1) 는 model_patterns "UCSC-C[0-9]+[ -]M[4-8]" / "C220[ -]M[4-8]" 로 `cisco_cimc.yml` (priority=100) 매칭

## 주의 (fixture 보강 필요)

- 이 fixture 의 system.json 에는 CIMC `FirmwareVersion` 필드가 없다 (adapter firmware match 는 FirmwareVersion 을 본다). BiosVersion 은 4.1 이다.
- 따라서 디렉터리 이름이 가리키는 "CIMC 3.x firmware → cisco_bmc fallback" 시나리오는 이 fixture 로는 재현되지 않는다. 그 fallback 을 검증하려면 `FirmwareVersion: "3.0(4j)"` 를 가진 별도 fixture 가 필요하다.
