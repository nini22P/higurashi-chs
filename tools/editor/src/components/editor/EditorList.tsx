import type { RefObject } from "react"
import {
  List,
  type ListImperativeAPI,
  type RowComponentProps,
} from "react-window"

import { AutoWidthInput } from "@/components/editor/AutoWidthInput"
import type { RowData } from "@/components/editor/types"

type EditorListProps = {
  listRef: RefObject<ListImperativeAPI | null>
  rowData: RowData
  rowCount: number
  rowHeight: number
}

type TokenPart = {
  type: "text" | "command"
  value: string
}

const COMMAND_TOKEN_RE = /@[A-Za-z0-9_/.|$-]+/g
const RUBY_TO_HUMAN_RE = /@b([^@.]+)\.@<([^@>]+)@>/g
const RUBY_TO_GAME_RE = /\[([^|\]]+)\|([^\]]+)\]/g

function getCell(row: string[], col: number): string {
  if (col < 0) {
    return ""
  }
  return row[col] ?? ""
}

function toHumanRuby(input: string): string {
  return input.replace(RUBY_TO_HUMAN_RE, "[$1|$2]")
}

function toGameRuby(input: string): string {
  return input.replace(RUBY_TO_GAME_RE, "@b$1.@<$2@>")
}

function splitTokenParts(input: string): TokenPart[] {
  const parts: TokenPart[] = []
  let lastIndex = 0

  for (const match of input.matchAll(COMMAND_TOKEN_RE)) {
    const matchIndex = match.index ?? 0
    const command = match[0]

    if (matchIndex > lastIndex) {
      parts.push({
        type: "text",
        value: input.slice(lastIndex, matchIndex),
      })
    }

    parts.push({ type: "command", value: command })
    lastIndex = matchIndex + command.length
  }

  if (lastIndex < input.length) {
    parts.push({
      type: "text",
      value: input.slice(lastIndex),
    })
  }

  if (parts.length === 0) {
    parts.push({ type: "text", value: "" })
  }

  return parts
}

function getTextParts(parts: TokenPart[]): string[] {
  const textParts = parts
    .filter((part) => part.type === "text")
    .map((part) => part.value)

  if (textParts.length === 0) {
    return [""]
  }

  return textParts
}

function mergeTextPartsByTemplate(
  parts: TokenPart[],
  textValues: string[]
): string {
  let textIndex = 0

  return parts
    .map((part) => {
      if (part.type === "command") {
        return part.value
      }

      const value = textValues[textIndex] ?? ""
      textIndex += 1
      return value
    })
    .join("")
}

function VirtualRow(props: RowComponentProps<RowData>) {
  const {
    index,
    style,
    ariaAttributes,
    rows,
    indexCol,
    sourceCol,
    sCol,
    translatedCol,
    editedTranslations,
    hideCommandTokens,
    onChangeTranslated,
  } = props

  const row = rows[index]
  const indexValue = getCell(row, indexCol)
  const sourceValue = getCell(row, sourceCol)
  const sValue = getCell(row, sCol)
  const translatedValue =
    editedTranslations[index] ?? getCell(row, translatedCol)

  const sourceDisplayValue = hideCommandTokens ? toHumanRuby(sValue) : sValue
  const translatedDisplayValue = hideCommandTokens
    ? toHumanRuby(translatedValue)
    : translatedValue

  const sourceParts = hideCommandTokens
    ? splitTokenParts(sourceDisplayValue)
    : null
  const translatedParts = hideCommandTokens
    ? splitTokenParts(translatedDisplayValue)
    : null

  const sourceTextParts = sourceParts ? getTextParts(sourceParts) : []
  const translatedTextParts = translatedParts
    ? getTextParts(translatedParts)
    : []
  const translatedSegmentValues = sourceTextParts.map(
    (_, segmentIndex) => translatedTextParts[segmentIndex] ?? ""
  )

  return (
    <div
      style={style}
      {...ariaAttributes}
      className="border-b border-border/70 bg-background/70 px-2.5 py-2"
    >
      <div
        className="mb-1 h-4 truncate font-mono text-[10px] tracking-tight text-muted-foreground"
        title={`index: ${indexValue} | source: ${sourceValue}`}
      >
        {indexValue} · {sourceValue}
      </div>

      {hideCommandTokens && sourceParts ? (
        <div className="overflow-x-auto overflow-y-hidden pb-0.5">
          <div className="w-max min-w-full">
            <div className="mb-1 flex gap-1">
              {sourceTextParts.map((sourceSegmentValue, textPartIndex) => (
                <AutoWidthInput
                  key={`src-${index}-${textPartIndex}`}
                  className="h-6 rounded-md border border-input/70 bg-muted/30 px-2 text-[13px] leading-6 text-muted-foreground outline-none"
                  value={sourceSegmentValue}
                  readOnly
                  title={sourceSegmentValue}
                />
              ))}
            </div>

            <div className="flex gap-1">
              {translatedSegmentValues.map(
                (translatedSegmentValue, textPartIndex) => {
                  const isLockedByPrevious =
                    textPartIndex > 0 &&
                    translatedSegmentValues[textPartIndex - 1].trim().length ===
                    0

                  return (
                    <AutoWidthInput
                      key={`tr-${index}-${textPartIndex}`}
                      className="h-6 rounded-md border border-input/80 bg-background px-2 text-[13px] leading-6 outline-none focus:border-primary/70 focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-45"
                      value={translatedSegmentValue}
                      disabled={isLockedByPrevious}
                      onChange={(event) => {
                        const nextValues = [...translatedSegmentValues]
                        nextValues[textPartIndex] = event.target.value
                        onChangeTranslated(
                          index,
                          toGameRuby(
                            mergeTextPartsByTemplate(sourceParts, nextValues)
                          )
                        )
                      }}
                    />
                  )
                }
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="mb-1 h-6">
            <input
              className="h-6 w-full rounded-md border border-input/70 bg-muted/30 px-2 text-[13px] leading-6 text-muted-foreground outline-none"
              value={sourceDisplayValue}
              readOnly
              title={sourceDisplayValue}
            />
          </div>

          <div className="h-6">
            <input
              className="h-6 w-full rounded-md border border-input/80 bg-background px-2 text-[13px] leading-6 outline-none focus:border-primary/70 focus:ring-2 focus:ring-primary/20"
              value={translatedDisplayValue}
              onChange={(event) =>
                onChangeTranslated(
                  index,
                  hideCommandTokens
                    ? toGameRuby(event.target.value)
                    : event.target.value
                )
              }
            />
          </div>
        </>
      )}
    </div>
  )
}

export function EditorList({
  listRef,
  rowData,
  rowCount,
  rowHeight,
}: EditorListProps) {
  return (
    <div className="min-h-0 overflow-auto rounded-md border border-border/70 bg-card/40">
      <List
        listRef={listRef}
        rowComponent={VirtualRow}
        rowCount={rowCount}
        rowHeight={rowHeight}
        rowProps={rowData}
        overscanCount={8}
        style={{ height: "100%" }}
      />
    </div>
  )
}
