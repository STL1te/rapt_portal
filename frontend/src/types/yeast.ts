export type Yeast = {
  id: string
  name: string | null
  product_id: string | null
  laboratory: string | null
  type: string | null
  form: string | null
  min_temperature: number | null
  max_temperature: number | null
  flocculation: string | null
  attenuation: number | null
  notes: string | null
  is_global: boolean
  archived: boolean
}
