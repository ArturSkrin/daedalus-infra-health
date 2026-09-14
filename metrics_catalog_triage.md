# Розбір каталогу метрик Triage

Джерело: `vitals-metrics-catalog.md` (Reference, 2026-09-14). Кожен показник з каталогу рознесено на три категорії:

- **Змінює рішення**: без нього одне з трьох рішень (втрутитись / запланувати / нічого) було б іншим.
- **Пояснює рішення**: показує, чому агент вирішив саме так. Місце в drill-in.
- **Не змінює нічого**: цікаве число, але жодне рішення від нього не залежить.

Усі поля з `tenantStats.tenants[<name>]` на `GET /v2/agent/status`, якщо не вказано інше.

## 1. Змінює рішення

| Поле | Ендпоінт | Яке рішення змінює | Поріг (чернетка) | Коментар |
| --- | --- | --- | --- | --- |
| `incidentMetrics.criticalOpen` | `/v2/agent/incidents` | втрутитись зараз | > 0 | Єдине поле, яке саме по собі дає "зараз". 0 тут справжній нуль. |
| `incidentMetrics.warningOpen` | `/v2/agent/incidents` | запланувати | > 0 | Відкрите, але не критичне. |
| `incidents.openNow` | status | зараз / запланувати | > 0 | Дублює два попередні, потрібен лише як перевірка узгодженості. |
| `golden.reqPerSec`, `golden.errPct`, `golden.p99Ms` | `/v2/agent/applications` | втрутитись зараз | errPct, зважений на blastRadius | Валідні лише якщо `golden.rateAsOfUnix` свіжий. Тенант-широкого значення немає, рахуємо самі. |
| `nodes[].blastRadius`, `nodes[].tier` | `/v2/agent/graph` | зараз або запланувати | tier 1 або blastRadius >= 0.5 піднімає warning до "зараз" | Це вага, не показник. На екрані не число, а "зачепить N сервісів, включно з X". |
| `precursorMatches[].confidence`, `.matchedSteps`, `.totalSteps` | `/v2/agent/analytics` | запланувати (майбутнє) | confidence >= 0.7 і matchedSteps/totalSteps >= 0.5 | Єдиний справжній прогноз у каталозі. Це наш показник у майбутнє. |
| `golden.memPsiPct`, `golden.cpuPsiPct`, `golden.ioPsiPct`, `golden.oomKills` | `/v2/agent/applications` | запланувати | PSI >= 1% або oomKills > 0 | Валідні лише при `golden.saturationAsOfUnix`. Це "найближче майбутнє" з фізики ресурсу. |
| `golden.memReqPct`, `golden.memPct` | `/v2/agent/applications` | запланувати | memReqPct >= 90% при PSI > 0 | Разом з PSI дає "памʼять насичується". |
| `repeatRatePct` | status | запланувати | > 20% | Проблема повертається, отже треба робота над коренем, а не гасіння. Показувати тільки при `sampledIncidents` > 0. |
| `serviceCoveragePct`, `servicesDark` | status | **блокує всі рішення** | coverage < 90% або dark > 0 | Довіра до даних. Якщо низька, рішення "спочатку полагодь збір". |
| `clusterAgentStats`, `gossip` | status | **блокує всі рішення** | агент кластера не підключений | Немає потоку, немає трекера. |
| `golden.*AsOfUnix` | `/v2/agent/applications` | **блокує показник** | старше 2 вікон | Свіжість кожного golden-блоку окремо. |
| `predictionPrecisionPct` | status | довіра до прогнозу | < 60%: прогноз показуємо сірим | Показувати тільки при `predictionHits + predictionMisses` > 0. |
| `ready`, `componentsReady` | `/v2/agent/applications` | втрутитись зараз | ready = false у tier 1 | Майже завжди вже відкрито як інцидент через `AppDegraded`, тому це підстраховка. |

## 2. Пояснює вже прийняте рішення

| Поле | Ендпоінт | Що пояснює |
| --- | --- | --- |
| `events.noise/signal/incident/unknown/drift` | status | Скільки шуму агент зʼїв замість нас. Аргумент довіри, не рішення. |
| `snrPct` | status | Те саме одним числом. У drill-in "довіра до агента". |
| `signalsByType` | status | Яка сімʼя сигналів домінує (log / red / use / k8s). Атрибуція. |
| `signalsHistory` | status | Текстура доби. Sparkline у drill-in, а також джерело для "як пройшла доба" через `.requests` і `.requestErrors`. |
| `autoResolvedPct` | status | Чому "нічого не робити" безпечне: агент сам закрив N%. |
| `precursorCoveragePct` | status | Скільки інцидентів агент передбачив заздалегідь. Пояснює довіру до прогнозу. |
| `predictionAvgLeadMs` | status | Скільки зазвичай є часу після попередження. Горизонт для "запланувати". |
| `mttrMs`, `mttdMs`, `incidentMetrics.medianTTR` | status, incidents | Цілі (goals), не рішення. Скидаються при рестарті core, тому на головному екрані небезпечні. |
| oldest open incident (`incidents[].firstSeen`) | incidents | Порядок у черзі, не саме рішення. |
| `incidents[].rca`, `.investigationPlan`, `.relatedEvents`, `.reopenCount` | incidents | Зміст drill-in відкритого інциденту. |
| `baselines[].mttrMean`, `.mttdMean`, `.blastRadiusMean`, `.reopenRate`, `.incidentRateWeek` | analytics | Норма для сервісу. Потрібна, щоб сказати "гірше, ніж зазвичай". |
| `patterns[]` | analytics | Який саме патерн збігся. Drill-in прогнозу. |
| `ownership.resolved/unattributed/contested` | status | Хто має реагувати. Змінює адресата, не рішення. |
| `golden.memNodePct`, `cpuNodePct`, денумінатори | applications | Пояснення насичення в drill-in. |
| `knownServices`, `unmappedServices`, `unmappedNames` | status | Пояснення низької довіри: які сервіси не в графі. |
| `baselines[].weeklyIncidentCounts` | analytics | Тижневий тренд для спокійного дня. |

## 3. Не змінює нічого

| Поле | Чому |
| --- | --- |
| `resolutionRatePct` | Частка закритих. Ретроспектива, рішення від неї не залежить. |
| `eventsPerIncident` | Показник якості класифікатора, не стану флоту. |
| `llmTokens`, `llmCalls`, `llmTokenRatio`, `llmRatioToday`, `llmRatio7d`, `llmBudget.byTenant` | Вартість самого агента, не інфраструктури. Це не "аномалія у витратах" з умови. |
| `retention` | Налаштування, не стан. |
| `nodes[].weight`, `nodes[].calls`, `.calledBy`, `edges[]` | Потрібні для обчислення blastRadius, самі по собі не читаються. |
| `incidentMetrics.infoOpen` | Інфо-інциденти не ведуть до жодного рішення. |

## 4. Пʼять показників головного екрану (оновлена чернетка)

| # | Показник (як читає інженер) | Рішення | З яких полів | Довіра |
| --- | --- | --- | --- | --- |
| 1 | **Стан флоту одним словом**: Спокійно / Запланувати / Зараз | усі три | criticalOpen дає Зараз; warningOpen, precursor >= 0.7, PSI >= 1%, repeatRate > 20% дають Запланувати; інакше Спокійно | ховається за сірим, якщо #4 червоний |
| 2 | **Користувачі зараз**: "всі запити проходять" / "страждає X% трафіку у N сервісах" | зараз | сума errPct x reqPerSec x blastRadius по apps зі свіжим rateAsOfUnix, плюс criticalOpen | свіжість rateAsOfUnix |
| 3 | **Що назріває** (майбутнє): "агент бачить 3 з 5 кроків до збою у payments, зазвичай є ~40 хв" / "нічого не назріває" | запланувати | precursorMatches, predictionAvgLeadMs, PSI + memReqPct | predictionPrecisionPct |
| 4 | **Чи можна вірити**: "бачимо 11 з 12 сервісів, дані 40 с" | блокує решту | serviceCoveragePct, servicesDark, clusterAgentStats, unmappedServices, *AsOfUnix | сам є довірою |
| 5 | **Як пройшла доба**: "агент закрив 7 сам, 0 повернулось, помилок як завжди" | нічого / запланувати | signalsHistory.requests і .requestErrors проти baselines, autoResolvedPct, repeatRatePct, incidentRateWeek | sampledIncidents > 0 |

## 5. Виявлені прогалини (для номінації)

1. **Немає події релізу або деплою.** Умова каже, що трекер відкривають "щоб зрозуміти, як пройшов реліз", але в API немає жодного маркера rollout. Найближче: `GraphDrift` і `AppStatusChanged`. Показник #5 доводиться будувати як "доба", а не "реліз". Потрібно: подія `Deploy` з часом і сервісом.
2. **Немає історії USE.** PSI і memPct є лише як поточний знімок на `/v2/agent/applications`. "Памʼять насичується третій день" з API порахувати неможливо, потрібен ряд у часі. `signalsHistory` має 5-хвилинні кошики лише для сигналів і запитів.
3. **Безпека невидима.** Умова називає порушення безпеки однією з трьох цілей, а каталог прямо каже: жодне поле не маркує security-подію. Потрібен фільтр за `source` або лічильник у `signalsByType`.
4. **Немає тенант-широкого RED.** Каталог визнає: rate, error%, p99 є лише per-app. Показник #2 рахується клієнтом, і формула зважування є нашою, не агента.
5. **Вартість інфраструктури відсутня.** Єдина вартість у каталозі, це LLM-токени самого агента. "Аномалії у витратах" з умови в API не представлені.
6. **Ретроспективні цілі скидаються при рестарті.** `mttrMs`, `mttdMs`, `resolutionRatePct`, `openNow` живуть у памʼяті core. Кільце може рухатись без змін у кластері. Аргумент проти винесення їх на головний екран.

## 6. Аргументи проти показників, які організатори вважають основними

- **"% of goals" у центрі екрана.** На еталонному екрані стоїть "100% of goals" поруч зі станом DEGRADED і відкритим критичним інцидентом. Цілі (awareness, warning, recovery) є метриками якості агента, а не стану флоту, тому вони можуть бути виконані на 100% в момент, коли треба бігти. Центр екрана має займати рішення.
- **SNR / Signal share як vital.** `snrPct` пояснює, скільки шуму відфільтровано, але жодне з трьох рішень від нього не залежить. Місце в drill-in як доказ довіри до агента.
- **Сирий лічильник подій у "короні"** (use 99, red 0, log 8 913, k8s 159 481). Умова прямо забороняє сирі величини на головному екрані; каталог сам називає це "raw feed, not a vital".
- **Пʼять вкладок** (Trends, Apps, Vitals, Cost, Secure) при ліміті "чотири максимум", причому Cost і Secure не мають полів в API.
