import type { CSSProperties, InputHTMLAttributes } from "react"
import { measureNaturalWidth, prepareWithSegments } from "@chenglou/pretext"

import { cn } from "@/lib/utils"

type AutoWidthInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value"
> & {
  value: string
  minWidthPx?: number
  maxWidthPx?: number
  horizontalPaddingPx?: number
  font?: string
}

const DEFAULT_FONT =
  '13px "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif'

const widthCache = new Map<string, number>()

function getMeasuredInputWidthPx(
  value: string,
  minWidthPx: number,
  maxWidthPx: number,
  horizontalPaddingPx: number,
  font: string
): number {
  const text = value.length > 0 ? value : " "
  const cacheKey = `${font}__${minWidthPx}__${maxWidthPx}__${horizontalPaddingPx}__${text}`

  const cached = widthCache.get(cacheKey)
  if (cached !== undefined) {
    return cached
  }

  const prepared = prepareWithSegments(text, font)
  const textWidth = measureNaturalWidth(prepared)
  const finalWidth = Math.min(
    maxWidthPx,
    Math.max(minWidthPx, Math.ceil(textWidth + horizontalPaddingPx))
  )

  widthCache.set(cacheKey, finalWidth)
  return finalWidth
}

export function AutoWidthInput({
  className,
  value,
  minWidthPx = 64,
  maxWidthPx = 2048,
  horizontalPaddingPx = 18,
  font = DEFAULT_FONT,
  style,
  ...props
}: AutoWidthInputProps) {
  const widthPx = getMeasuredInputWidthPx(
    value,
    minWidthPx,
    maxWidthPx,
    horizontalPaddingPx,
    font
  )

  const mergedStyle: CSSProperties = {
    ...style,
    width: `${widthPx}px`,
    minWidth: `${minWidthPx}px`,
  }

  return (
    <input
      className={cn(className)}
      value={value}
      style={mergedStyle}
      {...props}
    />
  )
}
