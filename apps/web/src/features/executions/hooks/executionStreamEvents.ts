import type { ExecutionDetail, ExecutionStep } from '../types'

export type ExecutionStreamEventName =
  | 'execution.status_changed'
  | 'step.status_changed'
  | 'execution.heartbeat'
  | 'stream.closed'

export interface ExecutionStreamEvent {
  event: ExecutionStreamEventName | string
  data: Record<string, unknown>
}

function readString(data: Record<string, unknown>, key: string) {
  const value = data[key]
  return typeof value === 'string' ? value : undefined
}

function readNullableString(data: Record<string, unknown>, key: string) {
  const value = data[key]
  return typeof value === 'string' || value === null ? value : undefined
}

function readNullableNumber(data: Record<string, unknown>, key: string) {
  const value = data[key]
  return typeof value === 'number' || value === null ? value : undefined
}

function patchStep(step: ExecutionStep, data: Record<string, unknown>): ExecutionStep {
  return {
    ...step,
    status: readString(data, 'status') ?? step.status,
    started_at: readNullableString(data, 'started_at') ?? step.started_at,
    finished_at: readNullableString(data, 'finished_at') ?? step.finished_at,
    exit_code: readNullableNumber(data, 'exit_code') ?? step.exit_code,
    error_message: readString(data, 'error_message') ?? step.error_message,
  }
}

export function applyStreamEvent(
  execution: ExecutionDetail | undefined,
  streamEvent: ExecutionStreamEvent
): ExecutionDetail | undefined {
  if (!execution) {
    return execution
  }

  if (streamEvent.event === 'execution.status_changed') {
    return {
      ...execution,
      status: readString(streamEvent.data, 'status') ?? execution.status,
      started_at: readNullableString(streamEvent.data, 'started_at') ?? execution.started_at,
      finished_at: readNullableString(streamEvent.data, 'finished_at') ?? execution.finished_at,
    }
  }

  if (streamEvent.event === 'step.status_changed') {
    const stepId = readString(streamEvent.data, 'step_id')

    return {
      ...execution,
      steps: execution.steps.map((step) => {
        return step.id === stepId ? patchStep(step, streamEvent.data) : step
      }),
    }
  }

  if (streamEvent.event === 'stream.closed') {
    return {
      ...execution,
      status: readString(streamEvent.data, 'final_status') ?? execution.status,
    }
  }

  return execution
}
