// The API contract. Nothing here is written by hand: api.gen.ts is generated
// from the backend's OpenAPI document (`npm run gen:types`), and CI fails when
// it is out of date. The frontend renders this model and decides nothing.
import type { components } from './api.gen'

type Schemas = components['schemas']

export type View = Schemas['View']
export type Indicator = Schemas['Indicator']
export type Drill = Schemas['Drill']
export type Fact = Schemas['Fact']
export type QueueItem = Schemas['QueueItem']
export type ScenarioListItem = Schemas['ScenarioListItem']

export type Level = Indicator['level']
export type Verdict = View['decision']['verdict']
export type IndicatorId = Indicator['id']
export type DrillTarget = IndicatorId | 'verdict'
