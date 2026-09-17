import {
  useEffect,
  useState,
} from "react";


type ScenarioListItem = {
  id: string;
  title: string;
  file: string;
  expected: string;
  actual: string;
  passed: boolean;
};


type Indicator = {
  id: string;
  title: string;
  state: string;
  detail: Record<string, unknown>;
};


type ScenarioView = {
  scenario: {
    id: string;
    title: string;
    story: string;
    tenant: string;
    now: string;
  };

  decision: {
    verdict: string;
    trigger: string;
    reason: string;
  };

  indicators: Indicator[];

  validation: {
    passed: boolean;

    expected: {
      verdict: string;
      states: Record<string, string>;
      reason?: string;
    };

    computed: {
      verdict: string;
      states: Record<string, string>;
    };
  };
};


function verdictClass(verdict: string) {
  switch (verdict) {
    case "СПОКІЙНО":
      return "verdict calm";

    case "ЗАПЛАНУВАТИ":
      return "verdict plan";

    case "ЗАРАЗ":
      return "verdict now";

    case "НАОСЛІП":
      return "verdict blind";

    default:
      return "verdict";
  }
}


function stateClass(state: string) {
  if (
    state === "Добре"
    || state === "Чисто"
    || state === "Повна"
    || state === "Спокійна"
    || state === "Осіла"
  ) {
    return "state good";
  }

  if (
    state === "Страждають"
    || state === "Тисне"
    || state === "Частково"
    || state === "Погіршилась"
    || state === "Назріває"
  ) {
    return "state warning";
  }

  if (state === "Зламано") {
    return "state bad";
  }

  return "state muted";
}


function formatValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length
      ? value.join(", ")
      : "—";
  }

  if (
    value === null
    || value === undefined
  ) {
    return "—";
  }

  if (typeof value === "boolean") {
    return value
      ? "yes"
      : "no";
  }

  return String(value);
}


function App() {
  const initialScenario =
    new URLSearchParams(
      window.location.search,
    ).get("scenario")
    || "s01_calm";

  const [
    scenarios,
    setScenarios,
  ] = useState<ScenarioListItem[]>([]);

  const [
    selected,
    setSelected,
  ] = useState(initialScenario);

  const [
    data,
    setData,
  ] = useState<ScenarioView | null>(null);

  const [
    loading,
    setLoading,
  ] = useState(true);

  const [
    error,
    setError,
  ] = useState<string | null>(null);


  useEffect(() => {
    fetch("/api/scenarios")
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            "Failed to load scenarios",
          );
        }

        return response.json();
      })
      .then(setScenarios)
      .catch((err) => {
        setError(err.message);
      });
  }, []);


  useEffect(() => {
    setLoading(true);
    setError(null);

    fetch(`/api/scenarios/${selected}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            "Failed to load scenario",
          );
        }

        return response.json();
      })
      .then(setData)
      .catch((err) => {
        setError(err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selected]);


  function changeScenario(
    scenario: string,
  ) {
    setSelected(scenario);

    const url = new URL(
      window.location.href,
    );

    url.searchParams.set(
      "scenario",
      scenario,
    );

    window.history.replaceState(
      {},
      "",
      url,
    );
  }


  if (error) {
    return (
      <main className="page">
        <section className="error-box">
          {error}
        </section>
      </main>
    );
  }


  return (
    <main className="page">
      <header className="header">
        <div>
          <div className="eyebrow">
            SELF-AWARE INFRASTRUCTURE
          </div>

          <h1>Daedalus</h1>

          <div className="subtitle">
            Infra Health Tracker
          </div>
        </div>

        <div className="scenario-picker">
          <label>
            DEMO SCENARIO
          </label>

          <select
            value={selected}
            onChange={(event) =>
              changeScenario(
                event.target.value,
              )
            }
          >
            {scenarios.map(
              (scenario) => (
                <option
                  key={scenario.id}
                  value={scenario.id}
                >
                  {scenario.title}
                </option>
              ),
            )}
          </select>
        </div>
      </header>


      {loading || !data ? (
        <section className="loading">
          Calculating infrastructure state…
        </section>
      ) : (
        <>
          <section className="scenario-meta">
            <span className="demo-pill">
              DEMO DATA
            </span>

            <span>
              {data.scenario.tenant}
            </span>

            <span>
              {data.scenario.now}
            </span>
          </section>


          <section className="hero">
            <div className="hero-label">
              Що робити?
            </div>

            <div
              className={verdictClass(
                data.decision.verdict,
              )}
            >
              {data.decision.verdict}
            </div>

            <div className="reason">
              {data.decision.reason}
            </div>

            <div className="story">
              {data.scenario.story}
            </div>
          </section>


          <section className="indicators">
            {data.indicators.map(
              (indicator) => (
                <article
                  className="indicator-card"
                  key={indicator.id}
                >
                  <div className="indicator-title">
                    {indicator.title}
                  </div>

                  <div
                    className={stateClass(
                      indicator.state,
                    )}
                  >
                    {indicator.state}
                  </div>

                  <details>
                    <summary>
                      Evidence
                    </summary>

                    <div className="evidence">
                      {Object.entries(
                        indicator.detail,
                      ).map(
                        ([key, value]) => (
                          <div
                            className="evidence-row"
                            key={key}
                          >
                            <span>
                              {key}
                            </span>

                            <strong>
                              {formatValue(
                                value,
                              )}
                            </strong>
                          </div>
                        ),
                      )}
                    </div>
                  </details>
                </article>
              ),
            )}
          </section>


          <section className="validation">
            <div className="validation-header">
              <div>
                <div className="eyebrow">
                  VALIDATION MODE
                </div>

                <h2>
                  Expected vs computed
                </h2>
              </div>

              <div
                className={
                  data.validation.passed
                    ? "pass"
                    : "fail"
                }
              >
                {data.validation.passed
                  ? "✓ PASS"
                  : "✗ FAIL"}
              </div>
            </div>


            <div className="validation-grid">
              <div>
                <span>Expected</span>

                <strong>
                  {
                    data.validation
                      .expected.verdict
                  }
                </strong>
              </div>

              <div>
                <span>Computed</span>

                <strong>
                  {
                    data.validation
                      .computed.verdict
                  }
                </strong>
              </div>
            </div>


            <div className="validation-states">
              {Object.entries(
                data.validation
                  .computed.states,
              ).map(
                ([key, computed]) => {
                  const expected =
                    data.validation
                      .expected.states[key];

                  return (
                    <div
                      className="validation-state"
                      key={key}
                    >
                      <span>{key}</span>

                      <strong>
                        {computed}
                      </strong>

                      <small>
                        expected: {expected}
                      </small>
                    </div>
                  );
                },
              )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}


export default App;
