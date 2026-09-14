# mock_data

Десять наборів мок-даних, по одному на зріз зі `scenarios.md`. Кожен файл повторює форму відповідей Triage API з каталогу метрик, щоб прототип читав мок і живий бекенд одним кодом.

## Файли

| Файл | Зріз | Очікуване рішення |
| --- | --- | --- |
| `s01_calm.json` | Спокійний ранок | СПОКІЙНО |
| `s02_release_settled.json` | Реліз осів | СПОКІЙНО |
| `s03_release_regressed.json` | Реліз регресував тихо | ЗАПЛАНУВАТИ |
| `s04_memory_pressure.json` | Памʼять насичується | ЗАПЛАНУВАТИ |
| `s05_agent_disconnected.json` | Агент кластера відвалився | НАОСЛІП |
| `s06_log_spike.json` | Сплеск логів без впливу | СПОКІЙНО |
| `s07_outage.json` | Checkout не працює | ЗАРАЗ |
| `s08_dark_services.json` | Два сервіси мовчать | ЗАПЛАНУВАТИ |
| `s09_precursor_imminent.json` | Агент бачить збій за 18 хвилин | ЗАРАЗ |
| `s10_low_precision.json` | Агент упевнений, але часто помиляється | СПОКІЙНО |

`index.json` містить список зрізів для перемикача в прототипі.

## Форма одного файлу

```
{
  "scenario": "s03_release_regressed",
  "title": "...", "tenant": "digital-purchases", "now": "2026-09-14T13:10:00+03:00",
  "story": "...",
  "expected": { "verdict": "ЗАПЛАНУВАТИ", "reason": "...", "states": { "users": "Добре", "forecast": "Чисто", "trust": "Повна", "day": "Погіршилась" } },
  "status":       { ...  GET /v2/agent/status  (tenantStats.tenants[tenant], clusterAgentStats, unmapped*) },
  "incidents":    { ...  GET /v2/agent/incidents?tenant= },
  "applications": [ ...  GET /v2/agent/applications?tenant= ],
  "graph":        { ...  GET /v2/agent/graph?tenant= },
  "analytics":    { ...  GET /v2/agent/analytics?tenant= }
}
```

Блок `expected` не є частиною API. Його читає лише перевірка і сторінка зрізу в прототипі.

Поля, яких немає в каталозі, але які потрібні для рендеру, додано мінімально і позначено в `generate.py`: `precursorMatches[].matched / remaining` (список кроків, у каталозі є лише лічильники) і `darkServices[]` у зрізі S08 (каталог дає лише `servicesDark` як число). Обидва є кандидатами в прогалини.

Каталог каже: відсутнє поле означає "не виміряно". Мок це відтворює: у batch-сервісів (`scheduler`, `backup`) немає блоку `reqPerSec / errPct / rateAsOfUnix`, у зрізі S08 їх немає в `applications` зовсім, у зрізі S05 усі `*AsOfUnix` застарілі на 47 хвилин.

## Як переглянути разом із прототипом

Прототип читає `mock_data/<id>.json` і перемикає зріз через параметр URL:

```
/?scenario=s03_release_regressed
```

Без параметра відкривається `s01_calm`. Перемикач зрізів у шапці прототипу бере список із `index.json`. Кожен екран показує рядок "DEMO DATA · <title>" і, у drill-in показника 1, блок `expected` поруч із тим, що прототип обчислив сам, щоб розбіжність було видно одразу.

## Як перевірити правила без прототипу

`evaluate.py` є еталонною реалізацією пʼяти показників із `metrics_spec.md`. Він читає всі зрізи, рахує стани та рішення і звіряє з `expected`.

```bash
python evaluate.py
```

```
scenario                  users       forecast    trust       day           verdict       ok
s01_calm                  Добре       Чисто       Повна       Спокійна      СПОКІЙНО      ✓
...
10/10 scenarios match metrics_spec.md
```

Один зріз із проміжними числами (частка помилок, свіжість, вікна доби):

```bash
python evaluate.py s03
```

Логіка прототипу має відтворювати `evaluate.py` один в один. Якщо правило в `metrics_spec.md` змінюється, змінюються обидва.

## Як перегенерувати

```bash
python generate.py
```

Усе детерміноване: спільна фікстура на 12 сервісів і seed на зріз. Перевизначення для зрізу лежать у функції з його номером у `generate.py`, решта успадковується від фікстури. Після зміни фікстури або порогів запустіть `evaluate.py`: він виходить із кодом 1, якщо хоч один зріз розійшовся з очікуванням.
