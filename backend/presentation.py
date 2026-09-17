from __future__ import annotations

from datetime import datetime


INDICATOR_NAMES = {
    "users": "Користувачі зараз",
    "forecast": "Що назріває",
    "trust": "Чи можна вірити",
    "day": "Як пройшла доба",
}


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def join_names(names: list[str]) -> str:
    if not names:
        return ""

    if len(names) == 1:
        return names[0]

    if len(names) == 2:
        return f"{names[0]} і {names[1]}"

    return (
        ", ".join(names[:-1])
        + f" і {names[-1]}"
    )


def service_node(data: dict, name: str) -> dict:
    for node in data["graph"]["nodes"]:
        if node["name"] == name:
            return node

    return {}


def app_by_name(data: dict, name: str) -> dict:
    for app in data["applications"]:
        if app["name"] == name:
            return app

    return {}


def precursor_for_service(
    data: dict,
    service: str | None,
) -> dict | None:
    if not service:
        return None

    for match in data["analytics"].get(
        "precursorMatches",
        [],
    ):
        if match.get("service") == service:
            return match

    return None


def human_reason(
    data: dict,
    result: dict,
) -> str:
    trigger = result["trigger"]
    detail = result["detail"]

    if trigger == "trust_blind":
        info = detail["trust"]

        minutes = info.get(
            "disconnectedMinutes",
        )

        if minutes is not None:
            return (
                "агент кластера не підключений "
                f"{minutes} хв, флот не видно"
            )

        return (
            "даних недостатньо, "
            "стану флоту не можна довіряти"
        )

    if trigger == "users_broken":
        info = detail["users"]

        broken = info.get(
            "tier1Broken",
            [],
        )

        service = (
            broken[0]
            if broken
            else (
                info.get("affected", ["сервіс"])[0]
                if info.get("affected")
                else "сервіс"
            )
        )

        node = service_node(
            data,
            service,
        )

        callers = node.get(
            "calledBy",
            [],
        )

        if callers:
            return (
                f"{service} не працює, "
                f"зачепить ще {len(callers)} сервіси"
            )

        return f"{service} не працює"

    if trigger == "critical_incident":
        incidents = data["incidents"].get(
            "incidents",
            [],
        )

        if incidents:
            service = incidents[0].get(
                "service",
                "інфраструктура",
            )

            return (
                f"{service}: відкрито "
                "критичний інцидент"
            )

        return "відкрито критичний інцидент"

    if trigger == "forecast_imminent":
        info = detail["forecast"]

        service = info.get("service")
        lead = info.get("leadMin")

        match = precursor_for_service(
            data,
            service,
        )

        if match:
            return (
                f"{service}: агент бачить "
                f"{match['matchedSteps']} з "
                f"{match['totalSteps']} кроків "
                "до збою, зазвичай є "
                f"~{lead} хв"
            )

        return (
            f"{service}: агент прогнозує "
            f"збій приблизно за {lead} хв"
        )

    if trigger == "users_escalated":
        info = detail["users"]

        names = join_names(
            info.get("affected", []),
        )

        return (
            f"{names}: користувачі вже "
            "відчувають проблему"
        )

    if trigger == "users_degraded":
        share = detail["users"].get(
            "failingShare",
        )

        return (
            f"помилки зачіпають приблизно "
            f"{share}% запитів"
        )

    if trigger == "forecast_risk":
        info = detail["forecast"]

        pressure = info.get(
            "pressure",
            [],
        )

        if pressure:
            service = pressure[0]

            app = app_by_name(
                data,
                service,
            )

            oom = (
                app.get("golden", {})
                .get("oomKills", 0)
            )

            if oom == 0:
                return (
                    f"{service}: памʼять "
                    "насичується, OOM ще не було"
                )

            return (
                f"{service}: ресурсний тиск "
                "вже призводить до OOM"
            )

        service = info.get(
            "service",
            "сервіс",
        )

        return (
            f"{service}: агент бачить "
            "ознаки майбутнього збою"
        )

    if trigger == "day_regressed":
        info = detail["day"]

        recent = info.get(
            "errRecent",
            0,
        )

        base = info.get(
            "errBase",
            0,
        )

        if base:
            ratio = round(
                recent / base,
                1,
            )

            return (
                f"помилок приблизно у "
                f"{ratio}× більше за норму "
                "за останні 2 год"
            )

        return (
            "рівень помилок за останні "
            "2 год погіршився"
        )

    if trigger == "warning_incident":
        return (
            "є відкритий warning-інцидент, "
            "потрібно запланувати перевірку"
        )

    if trigger == "trust_partial":
        tenant = (
            data["status"]["tenantStats"]
            ["tenants"][data["tenant"]]
        )

        dark = tenant.get(
            "darkServices",
            [],
        )

        names = [
            item["name"]
            for item in dark
        ]

        if names:
            now = parse(data["now"])

            hours = max(
                1,
                round(
                    max(
                        (
                            now
                            - parse(item["lastEventAt"])
                        ).total_seconds()
                        for item in dark
                    )
                    / 3600
                ),
            )

            return (
                f"{join_names(names)} мовчать "
                f"~{hours} год: здорові чи "
                "мертві, невідомо"
            )

        return (
            "частину сервісів не видно, "
            "дані неповні"
        )

    # calm
    day_state = result["states"]["day"]
    forecast_state = result["states"]["forecast"]

    if day_state == "Осіла":
        return (
            "сплеск помилок осів, "
            "відкритих інцидентів немає"
        )

    if (
        forecast_state == "Тисне"
        and detail["forecast"].get(
            "downgraded"
        )
    ):
        precision = (
            detail["forecast"]
            .get("precision")
        )

        return (
            "усе в нормі; агент бачить "
            "слабкий сигнал, але його точність "
            f"лише {precision}%"
        )

    tenant = (
        data["status"]["tenantStats"]
        ["tenants"][data["tenant"]]
    )

    signal_types = tenant.get(
        "signalsByType",
        {},
    )

    if (
        signal_types.get("log", 0) > 1000
        and signal_types.get("red", 0) == 0
    ):
        return (
            "у логах сильний шум, "
            "але користувачів це не зачіпає"
        )

    return (
        "усе в нормі, за добу "
        "нічого критичного не сталось"
    )


def indicator_cards(
    result: dict,
) -> list[dict]:
    cards = []

    for key in (
        "users",
        "forecast",
        "trust",
        "day",
    ):
        cards.append(
            {
                "id": key,
                "title": INDICATOR_NAMES[key],
                "state": result["states"][key],
                "detail": (
                    result["detail"].get(key, {})
                ),
            }
        )

    return cards


def build_view(
    data: dict,
    result: dict,
) -> dict:
    expected = data["expected"]

    passed = (
        result["verdict"]
        == expected["verdict"]
        and result["states"]
        == expected["states"]
    )

    return {
        "scenario": {
            "id": data["scenario"],
            "title": data["title"],
            "story": data["story"],
            "tenant": data["tenant"],
            "now": data["now"],
        },
        "decision": {
            "verdict": result["verdict"],
            "trigger": result["trigger"],
            "reason": human_reason(
                data,
                result,
            ),
        },
        "indicators": indicator_cards(
            result,
        ),
        "validation": {
            "passed": passed,
            "expected": {
                "verdict": expected["verdict"],
                "states": expected["states"],
                "reason": expected.get("reason"),
            },
            "computed": {
                "verdict": result["verdict"],
                "states": result["states"],
            },
        },
    }
