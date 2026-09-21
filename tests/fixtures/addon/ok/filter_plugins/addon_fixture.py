"""엔진 테스트용 role filter — role 을 include 하면 자동 등록되는지 확인한다."""


class FilterModule:
    def filters(self):
        return {"addon_fixture_probe": lambda value: f"fixture:{value}"}
