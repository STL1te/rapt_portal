export type BatchVolume = {
  id: number
  batch_id: number
  recorded_on: string // YYYY-MM-DD
  volume_l: number
}

export type BatchInput = {
  name: string
  bottled_on: string
  volume_l: number
  carbonation_until: string
  conditioning_until: string
  finished_on: string | null
  notes: string | null
}

export type Batch = BatchInput & {
  id: number
  volumes: BatchVolume[]
  remaining_l: number
}
