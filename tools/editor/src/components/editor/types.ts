export type CsvData = {
  headers: string[]
  rows: string[][]
}

export type RowData = {
  rows: string[][]
  indexCol: number
  sourceCol: number
  sCol: number
  translatedCol: number
  editedTranslations: Record<number, string>
  hideCommandTokens: boolean
  onChangeTranslated: (rowIndex: number, value: string) => void
}

export type NavItem = {
  rowIndex: number
  text: string
  indexText: string
}

export type SaveCsvPayload = {
  filePath: string
  editedTranslations: Record<number, string>
}
