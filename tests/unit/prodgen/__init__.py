# tests/unit/prodgen 를 패키지로 두는 이유 (2026-10-03): 이 디렉터리의 conftest.py 가 모듈 이름 `conftest` 로 적재되면
# e2e 테스트의 `from conftest import …`(tests/e2e/conftest.py 의 helper) 가 엉뚱한 conftest 를 가리켜 수집이 깨진다 (G14 run 3/4).
# 패키지면 `prodgen.conftest` 로 적재되어 충돌하지 않는다.
