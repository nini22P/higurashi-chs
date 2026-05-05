import type { NavItem } from "@/components/editor/types"

type NavPanelProps = {
  items: NavItem[]
  onJump: (rowIndex: number) => void
}

export function NavPanel({ items, onJump }: NavPanelProps) {
  return (
    <div className="min-h-0 rounded-md border border-border/70 bg-card/70">
      <div className="h-full overflow-auto p-1">
        {items.length === 0 ? (
          <div className="px-2 py-1 text-xs text-muted-foreground">
            无 saveinfo 条目
          </div>
        ) : (
          items.map((item) => (
            <button
              key={`nav-${item.rowIndex}`}
              type="button"
              className="mb-1 flex h-6 w-full items-center gap-1 rounded-md border border-border/70 px-2 text-xs hover:bg-muted/60"
              title={item.text}
              onClick={() => onJump(item.rowIndex)}
            >
              <span className="min-w-0 flex-1 truncate text-left">
                {item.text || `(row ${item.rowIndex})`}
              </span>
              <span className="shrink-0 font-mono text-muted-foreground">
                {item.indexText}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
