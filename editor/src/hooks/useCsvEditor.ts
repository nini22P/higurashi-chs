import { useMemo, useState } from "react"
import { invoke } from "@tauri-apps/api/core"
import { open } from "@tauri-apps/plugin-dialog"

import type {
  CsvData,
  NavItem,
  RowData,
  SaveCsvPayload,
} from "@/components/editor/types"

function getCell(row: string[], col: number): string {
  if (col < 0) {
    return ""
  }
  return row[col] ?? ""
}

export function useCsvEditor() {
  const [filePath, setFilePath] = useState<string | null>(null)
  const [fileName, setFileName] = useState("")
  const [csvData, setCsvData] = useState<CsvData | null>(null)
  const [editedTranslations, setEditedTranslations] = useState<
    Record<number, string>
  >({})
  const [error, setError] = useState("")
  const [isSaving, setIsSaving] = useState(false)
  const [hideCommandTokens, setHideCommandTokens] = useState(false)

  const translatedColIndex = useMemo(() => {
    if (!csvData) {
      return -1
    }
    return csvData.headers.indexOf("translated")
  }, [csvData])

  const rowData = useMemo<RowData | null>(() => {
    if (!csvData || translatedColIndex < 0) {
      return null
    }

    const indexCol = csvData.headers.indexOf("index")
    const sourceCol = csvData.headers.indexOf("source")
    const sCol = csvData.headers.indexOf("s")

    return {
      rows: csvData.rows,
      indexCol,
      sourceCol,
      sCol,
      translatedCol: translatedColIndex,
      editedTranslations,
      hideCommandTokens,
      onChangeTranslated: (rowIndex: number, value: string) => {
        setEditedTranslations((prev) => ({
          ...prev,
          [rowIndex]: value,
        }))
      },
    }
  }, [csvData, translatedColIndex, editedTranslations, hideCommandTokens])

  const navItems = useMemo<NavItem[]>(() => {
    if (!csvData) {
      return []
    }

    const sourceCol = csvData.headers.indexOf("source")
    const sCol = csvData.headers.indexOf("s")
    const indexCol = csvData.headers.indexOf("index")

    if (sourceCol < 0 || sCol < 0) {
      return []
    }

    return csvData.rows
      .map((row, rowIndex) => ({
        rowIndex,
        source: getCell(row, sourceCol),
        text: getCell(row, sCol),
        indexText: getCell(row, indexCol) || String(rowIndex),
      }))
      .filter((item) => item.source === "saveinfo")
      .map((item) => ({
        rowIndex: item.rowIndex,
        text: item.text,
        indexText: item.indexText,
      }))
  }, [csvData])

  async function openCsv() {
    setError("")

    try {
      const selected = await open({
        multiple: false,
        directory: false,
        filters: [
          {
            name: "CSV Files",
            extensions: ["csv"],
          },
        ],
      })

      if (!selected || Array.isArray(selected)) {
        return
      }

      const parsed = await invoke<CsvData>("load_csv", {
        filePath: selected,
      })

      if (parsed.headers.length === 0) {
        setError("CSV 为空或格式无效。")
        return
      }

      if (!parsed.headers.includes("translated")) {
        setError("CSV 缺少 translated 列，无法编辑。")
        return
      }

      setFilePath(selected)
      setFileName(selected.split(/[/\\]/).pop() ?? selected)
      setCsvData(parsed)
      setEditedTranslations({})
    } catch {
      setError("未打开文件。")
    }
  }

  async function saveCsv() {
    if (!filePath || !csvData || translatedColIndex < 0) {
      setError("请先打开 CSV。")
      return
    }

    setError("")
    setIsSaving(true)

    try {
      const nonEmptyEdits = Object.fromEntries(
        Object.entries(editedTranslations).filter(
          ([, value]) => value.trim().length > 0
        )
      ) as Record<number, string>

      const hasEdits = Object.keys(nonEmptyEdits).length > 0
      if (!hasEdits) {
        return
      }

      const payload: SaveCsvPayload = {
        filePath,
        editedTranslations: nonEmptyEdits,
      }

      await invoke("save_csv", { payload })

      const updatedRows = csvData.rows.map((row, rowIndex) => {
        const editedValue = nonEmptyEdits[rowIndex]
        if (editedValue === undefined) {
          return row
        }

        const nextRow = [...row]
        nextRow[translatedColIndex] = editedValue
        return nextRow
      })

      setCsvData({
        headers: csvData.headers,
        rows: updatedRows,
      })
      setEditedTranslations({})
    } catch {
      setError("保存失败，请确认文件权限。")
    } finally {
      setIsSaving(false)
    }
  }

  return {
    filePath,
    fileName,
    csvData,
    rowData,
    navItems,
    translatedColIndex,
    error,
    isSaving,
    hideCommandTokens,
    setHideCommandTokens,
    canSave: Boolean(csvData && filePath) && !isSaving,
    openCsv,
    saveCsv,
  }
}
