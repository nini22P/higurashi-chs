import { Button } from "@/components/ui/button"

type EditorTopBarProps = {
  fileName: string
  canSave: boolean
  isSaving: boolean
  hideCommandTokens: boolean
  onToggleHideCommandTokens: (checked: boolean) => void
  onOpen: () => void
  onSave: () => void
}

export function EditorTopBar({
  fileName,
  canSave,
  isSaving,
  hideCommandTokens,
  onToggleHideCommandTokens,
  onOpen,
  onSave,
}: EditorTopBarProps) {
  return (
    <div className="flex h-8 items-center gap-2 rounded-md border border-border/70 bg-card pr-0.5 pl-2">
      <span className="truncate text-xs text-muted-foreground">
        {fileName || "未打开文件"}
      </span>

      <label className="ml-auto flex items-center gap-1 rounded px-1 text-[11px] text-muted-foreground select-none">
        <input
          type="checkbox"
          className="h-3.5 w-3.5"
          checked={hideCommandTokens}
          onChange={(event) => onToggleHideCommandTokens(event.target.checked)}
        />
        隐藏指令
      </label>

      <div className="flex items-center gap-0.5">
        <Button size="sm" onClick={onOpen}>
          打开
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onSave}
          disabled={!canSave}
        >
          {isSaving ? "保存中..." : "保存"}
        </Button>
      </div>
    </div>
  )
}
