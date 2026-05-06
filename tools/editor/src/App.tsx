import { useListRef } from "react-window"

import { EditorList } from "@/components/editor/EditorList"
import { NavPanel } from "@/components/editor/NavPanel"
import { EditorTopBar } from "@/components/editor/EditorTopBar"
import { useCsvEditor } from "@/hooks/useCsvEditor"

const ROW_HEIGHT = 92

function App() {
  const listRef = useListRef(null)
  const {
    fileName,
    csvData,
    rowData,
    navItems,
    translatedColIndex,
    error,
    isSaving,
    hideCommandTokens,
    setHideCommandTokens,
    canSave,
    openCsv,
    saveCsv,
  } = useCsvEditor()

  return (
    <div className="flex h-svh flex-col gap-2 bg-background p-2">
      <EditorTopBar
        fileName={fileName}
        canSave={canSave}
        isSaving={isSaving}
        hideCommandTokens={hideCommandTokens}
        onToggleHideCommandTokens={setHideCommandTokens}
        onOpen={openCsv}
        onSave={saveCsv}
      />

      {error ? <div className="text-xs text-red-600">{error}</div> : null}

      {!csvData ? (
        <div className="text-sm text-muted-foreground"></div>
      ) : translatedColIndex < 0 || !rowData ? (
        <div className="text-sm text-red-600">
          当前 CSV 不含 translated 列。
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[220px_minmax(0,1fr)] gap-2">
          <NavPanel
            items={navItems}
            onJump={(rowIndex) =>
              listRef.current?.scrollToRow({
                index: rowIndex,
                align: "start",
                behavior: "auto",
              })
            }
          />
          <EditorList
            listRef={listRef}
            rowData={rowData}
            rowCount={csvData.rows.length}
            rowHeight={ROW_HEIGHT}
          />
        </div>
      )}
    </div>
  )
}

export default App
