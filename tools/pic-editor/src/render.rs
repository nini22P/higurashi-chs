use crate::model::{hex_to_rgba, rgba_to_hex_rgba, Align, PicItem, TextBlock, Valign};
use ab_glyph::{Font, FontVec, GlyphId, PxScale, ScaleFont};
use image::{imageops::FilterType, Rgba, RgbaImage};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

#[derive(Default)]
pub struct FontCache {
    inner: RwLock<HashMap<PathBuf, Arc<FontVec>>>,
}

impl FontCache {
    pub fn get(
        &self,
        font_spec: &str,
        fonts_map: &BTreeMap<String, String>,
        font_dir: &str,
    ) -> Result<Arc<FontVec>, String> {
        let name = fonts_map
            .get(font_spec)
            .map(|s| s.as_str())
            .unwrap_or(font_spec);
        if name.trim().is_empty() {
            return Err(format!("Empty font name for '{font_spec}'"));
        }
        let p = Path::new(name);
        let full = if p.is_absolute() || font_dir.trim().is_empty() {
            p.to_path_buf()
        } else {
            Path::new(font_dir.trim()).join(p)
        };

        if let Some(found) = self.inner.read().unwrap().get(&full) {
            return Ok(Arc::clone(found));
        }

        if !full.is_file() {
            return Err(format!(
                "Font not found: {} (for '{font_spec}')",
                full.display()
            ));
        }
        let bytes =
            std::fs::read(&full).map_err(|e| format!("Failed to read {}: {e}", full.display()))?;
        let font = FontVec::try_from_vec(bytes)
            .map_err(|e| format!("Invalid font {}: {e}", full.display()))?;
        let arc = Arc::new(font);
        self.inner.write().unwrap().insert(full, Arc::clone(&arc));
        Ok(arc)
    }
}

pub fn parse_spans(line: &str, default_color: [u8; 4]) -> Vec<(String, [u8; 4])> {
    let red = [255, 0, 0, 255];
    let mut out = Vec::new();
    let mut rest = line;
    while let Some(start) = rest.find("[r]") {
        if start > 0 {
            out.push((rest[..start].to_string(), default_color));
        }
        let after = &rest[start + 3..];
        if let Some(end) = after.find("[/r]") {
            if end > 0 {
                out.push((after[..end].to_string(), red));
            }
            rest = &after[end + 4..];
        } else {
            out.push((rest[start..].to_string(), default_color));
            rest = "";
            break;
        }
    }
    if !rest.is_empty() {
        out.push((rest.to_string(), default_color));
    }
    out
}

fn measure_line<F: Font>(scaled: &ab_glyph::PxScaleFont<&F>, line: &str, char_gap: i32) -> f32 {
    let spans = parse_spans(line, [255, 255, 255, 255]);
    let mut w = 0.0f32;
    let mut prev: Option<GlyphId> = None;
    let mut count = 0usize;
    for (txt, _) in spans {
        for ch in txt.chars() {
            let id = scaled.glyph_id(ch);
            if char_gap == 0 {
                if let Some(p) = prev {
                    w += scaled.kern(p, id);
                }
            } else if count > 0 {
                w += char_gap as f32;
            }
            w += scaled.h_advance(id);
            prev = Some(id);
            count += 1;
        }
    }
    w
}

#[inline]
fn blend_pixel(dst: &mut [u8], src_rgb: [u8; 3], alpha: f32) {
    if alpha <= 0.0 {
        return;
    }
    let sa = alpha.clamp(0.0, 1.0);
    let da = dst[3] as f32 / 255.0;
    let out_a = sa + da * (1.0 - sa);
    if out_a <= 0.0 {
        return;
    }
    for i in 0..3 {
        let sc = src_rgb[i] as f32;
        let dc = dst[i] as f32;
        dst[i] = ((sc * sa + dc * da * (1.0 - sa)) / out_a)
            .round()
            .clamp(0.0, 255.0) as u8;
    }
    dst[3] = (out_a * 255.0).round().clamp(0.0, 255.0) as u8;
}

pub fn safe_composite(dst: &mut RgbaImage, src: &RgbaImage, ox: i32, oy: i32) {
    let dw = dst.width() as i32;
    let dh = dst.height() as i32;
    let sw = src.width() as i32;
    let sh = src.height() as i32;

    let x0 = ox.max(0);
    let y0 = oy.max(0);
    let x1 = (ox + sw).min(dw);
    let y1 = (oy + sh).min(dh);
    if x1 <= x0 || y1 <= y0 {
        return;
    }

    let dst_raw = dst.as_mut();
    let src_raw = src.as_raw();
    for dy in y0..y1 {
        let sy = (dy - oy) as usize;
        let dst_row = (dy as usize) * (dw as usize) * 4;
        let src_row = sy * (sw as usize) * 4;
        for dx in x0..x1 {
            let sx = (dx - ox) as usize;
            let s_idx = src_row + sx * 4;
            let a = src_raw[s_idx + 3];
            if a == 0 {
                continue;
            }
            let d_idx = dst_row + (dx as usize) * 4;
            if a == 255 {
                dst_raw[d_idx..d_idx + 4].copy_from_slice(&src_raw[s_idx..s_idx + 4]);
            } else {
                blend_pixel(
                    &mut dst_raw[d_idx..d_idx + 4],
                    [src_raw[s_idx], src_raw[s_idx + 1], src_raw[s_idx + 2]],
                    a as f32 / 255.0,
                );
            }
        }
    }
}

pub fn render_block_layer(
    block: &TextBlock,
    fonts_map: &BTreeMap<String, String>,
    font_dir: &str,
    cache: &FontCache,
) -> Result<(Option<RgbaImage>, [i32; 4]), String> {
    let normalized = block.translation.replace("\\n", "\n");
    let raw_tr = normalized.trim_matches(|c| c == '\r' || c == '\n');
    if raw_tr.trim().is_empty() {
        return Ok((
            None,
            [block.x - 20, block.y - 20, block.x + 20, block.y + 20],
        ));
    }

    let font = cache.get(&block.font, fonts_map, font_dir)?;
    let sz = block.font_size.max(8) as f32;
    let scaled = font.as_scaled(PxScale::from(sz));
    let fg_rgba = hex_to_rgba(&block.color, [255, 255, 255, 255]);

    let lines: Vec<&str> = raw_tr.split('\n').collect();
    let mut line_items: Vec<(&str, f32)> = Vec::new();
    let mut cur_y = 0.0f32;
    for (i, line) in lines.iter().enumerate() {
        if line.trim().is_empty() {
            cur_y += block.blank_height as f32;
            continue;
        }
        line_items.push((line, cur_y));
        if i + 1 < lines.len() {
            cur_y += sz + block.line_gap as f32;
        }
    }

    if line_items.is_empty() {
        return Ok((
            None,
            [block.x - 20, block.y - 20, block.x + 20, block.y + 20],
        ));
    }

    let line_widths: Vec<f32> = line_items
        .iter()
        .map(|(l, _)| measure_line(&scaled, l, block.char_gap))
        .collect();
    let max_w = line_widths.iter().copied().fold(sz, f32::max);
    let span_h = line_items.last().unwrap().1 - line_items.first().unwrap().1 + sz * 2.0;

    let pad = (sz as i32).max(16);
    let tmp_w = ((max_w.ceil() as i32) + pad * 2).max(128) as u32;
    let tmp_h = ((span_h.ceil() as i32) + pad * 2).max(128) as u32;
    let mut tmp = RgbaImage::from_pixel(tmp_w, tmp_h, Rgba([0, 0, 0, 0]));
    let tmp_raw = tmp.as_mut();

    let anchor_x = match block.align {
        Align::Center => (tmp_w / 2) as f32,
        Align::Left => pad as f32,
        Align::Right => (tmp_w as i32 - pad) as f32,
    };
    let base_y = pad as f32 + scaled.ascent();

    for ((line, dy), lw) in line_items.iter().zip(line_widths.iter()) {
        let mut pen_x = match block.align {
            Align::Center => anchor_x - lw / 2.0,
            Align::Left => anchor_x,
            Align::Right => anchor_x - lw,
        };
        let pen_y = base_y + dy;
        let mut prev: Option<GlyphId> = None;
        let mut count = 0usize;

        for (span_text, span_col) in parse_spans(line, fg_rgba) {
            let col_a = span_col[3] as f32 / 255.0;
            for ch in span_text.chars() {
                let id = scaled.glyph_id(ch);
                if block.char_gap == 0 {
                    if let Some(p) = prev {
                        pen_x += scaled.kern(p, id);
                    }
                } else if count > 0 {
                    pen_x += block.char_gap as f32;
                }
                let glyph =
                    id.with_scale_and_position(PxScale::from(sz), ab_glyph::point(pen_x, pen_y));
                if let Some(outlined) = scaled.outline_glyph(glyph) {
                    let bb = outlined.px_bounds();
                    outlined.draw(|gx, gy, cov| {
                        let px = bb.min.x as i32 + gx as i32;
                        let py = bb.min.y as i32 + gy as i32;
                        if px >= 0 && py >= 0 && px < tmp_w as i32 && py < tmp_h as i32 {
                            let idx = (py as usize * tmp_w as usize + px as usize) * 4;
                            blend_pixel(
                                &mut tmp_raw[idx..idx + 4],
                                [span_col[0], span_col[1], span_col[2]],
                                cov * col_a,
                            );
                        }
                    });
                }
                pen_x += scaled.h_advance(id);
                prev = Some(id);
                count += 1;
            }
        }
    }

    let mut min_x = tmp_w;
    let mut min_y = tmp_h;
    let mut max_x = 0u32;
    let mut max_y = 0u32;
    let mut any = false;
    for y in 0..tmp_h {
        let row = y as usize * tmp_w as usize * 4;
        for x in 0..tmp_w {
            if tmp_raw[row + x as usize * 4 + 3] > 0 {
                any = true;
                min_x = min_x.min(x);
                min_y = min_y.min(y);
                max_x = max_x.max(x);
                max_y = max_y.max(y);
            }
        }
    }
    if !any {
        return Ok((
            None,
            [block.x - 20, block.y - 20, block.x + 20, block.y + 20],
        ));
    }

    let mut cropped =
        image::imageops::crop_imm(&tmp, min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            .to_image();
    if (block.scale_x - 1.0).abs() > 1e-3 {
        let new_w = ((cropped.width() as f32 * block.scale_x).round() as u32).max(1);
        cropped = image::imageops::resize(&cropped, new_w, cropped.height(), FilterType::Lanczos3);
    }

    let cw = cropped.width() as i32;
    let ch = cropped.height() as i32;
    let ox = match block.align {
        Align::Center => block.x - cw / 2,
        Align::Left => block.x,
        Align::Right => block.x - cw,
    };
    let oy = match block.valign {
        Valign::Middle => block.y - ch / 2,
        Valign::Top => block.y,
        Valign::Bottom => block.y - ch,
    };

    Ok((Some(cropped), [ox, oy, ox + cw, oy + ch]))
}

#[inline]
pub fn rects_overlap(a: [i32; 4], b: [i32; 4], pad: i32) -> bool {
    (a[0] - pad) <= b[2] && (a[2] + pad) >= b[0] && (a[1] - pad) <= b[3] && (a[3] + pad) >= b[1]
}

fn fill_rect_rgba(img: &mut RgbaImage, rect: [i32; 4], pad: i32, color: [u8; 4]) {
    let w = img.width() as i32;
    let h = img.height() as i32;
    let x0 = (rect[0] - pad).clamp(0, w);
    let y0 = (rect[1] - pad).clamp(0, h);
    let x1 = (rect[2] + 1 + pad).clamp(0, w);
    let y1 = (rect[3] + 1 + pad).clamp(0, h);
    let raw = img.as_mut();
    for y in y0..y1 {
        let row = (y as usize) * (w as usize) * 4;
        for x in x0..x1 {
            let idx = row + (x as usize) * 4;
            raw[idx..idx + 4].copy_from_slice(&color);
        }
    }
}

pub fn render_item(
    item: &PicItem,
    fonts_map: &BTreeMap<String, String>,
    font_dir: &str,
    orig_img: Option<&RgbaImage>,
    orig_boxes: Option<&[[i32; 4]]>,
    cache: &FontCache,
) -> Result<(RgbaImage, Vec<[i32; 4]>), String> {
    let bg = hex_to_rgba(&item.bg_color, [0, 0, 0, 255]);
    let mut img = match orig_img {
        Some(orig) => orig.clone(),
        None => RgbaImage::from_pixel(item.width.max(1), item.height.max(1), Rgba(bg)),
    };

    let mut layers: Vec<(Option<RgbaImage>, [i32; 4])> = Vec::with_capacity(item.blocks.len());
    for block in &item.blocks {
        layers.push(render_block_layer(block, fonts_map, font_dir, cache)?);
    }

    if orig_img.is_some() {
        let computed_boxes;
        let boxes: &[[i32; 4]] = match orig_boxes {
            Some(b) => b,
            None => {
                computed_boxes = detect_line_boxes(&img);
                &computed_boxes
            }
        };
        for &ob in boxes {
            let hit = layers
                .iter()
                .any(|(layer_opt, r)| layer_opt.is_some() && rects_overlap(*r, ob, 4));
            if hit {
                fill_rect_rgba(&mut img, ob, 2, bg);
            }
        }
    }

    let mut rects = Vec::with_capacity(layers.len());
    for (layer_opt, r) in layers {
        if let Some(layer) = layer_opt {
            safe_composite(&mut img, &layer, r[0], r[1]);
        }
        rects.push(r);
    }
    Ok((img, rects))
}

fn bands_1d(mask: &[bool], gap: usize) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start: Option<usize> = None;
    let mut last = 0usize;
    for (i, &v) in mask.iter().enumerate() {
        if v {
            match start {
                None => {
                    start = Some(i);
                    last = i;
                }
                Some(s) => {
                    if i - last > gap {
                        out.push((s, last));
                        start = Some(i);
                    }
                    last = i;
                }
            }
        }
    }
    if let Some(s) = start {
        out.push((s, last));
    }
    out
}

pub fn detect_line_boxes(img: &RgbaImage) -> Vec<[i32; 4]> {
    let w = img.width() as usize;
    let h = img.height() as usize;
    if w == 0 || h == 0 {
        return Vec::new();
    }
    let raw = img.as_raw();
    let total = w * h;
    let trans_cnt = (0..total).filter(|&i| raw[i * 4 + 3] == 0).count();
    let use_alpha = (trans_cnt as f32 / total as f32) > 0.05;

    let mut mask = vec![false; total];
    if use_alpha {
        for i in 0..total {
            mask[i] = raw[i * 4 + 3] > 16;
        }
    } else {
        let mut corners: Vec<[i16; 3]> = Vec::new();
        let cw = 10.min(w);
        let ch = 10.min(h);
        for &(bx, by) in &[(0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch)] {
            for y in by..by + ch {
                for x in bx..bx + cw {
                    let idx = (y * w + x) * 4;
                    corners.push([raw[idx] as i16, raw[idx + 1] as i16, raw[idx + 2] as i16]);
                }
            }
        }
        let mut bg = [0i16; 3];
        for c in 0..3 {
            let mut vals: Vec<i16> = corners.iter().map(|p| p[c]).collect();
            vals.sort_unstable();
            bg[c] = vals[vals.len() / 2];
        }
        let mean: f32 = corners
            .iter()
            .flat_map(|p| p.iter().map(|&v| v as f32))
            .sum::<f32>()
            / (corners.len() * 3) as f32;
        let var: f32 = corners
            .iter()
            .flat_map(|p| p.iter().map(|&v| (v as f32 - mean).powi(2)))
            .sum::<f32>()
            / (corners.len() * 3) as f32;
        if var.sqrt() > 5.0 {
            return Vec::new();
        }
        for i in 0..total {
            let idx = i * 4;
            let d = (raw[idx] as i16 - bg[0])
                .abs()
                .max((raw[idx + 1] as i16 - bg[1]).abs())
                .max((raw[idx + 2] as i16 - bg[2]).abs());
            mask[i] = d > 20;
        }
    }

    let row_has: Vec<bool> = (0..h)
        .map(|y| mask[y * w..(y + 1) * w].iter().any(|&v| v))
        .collect();
    let row_bands = bands_1d(&row_has, 6);
    let mut boxes = Vec::new();
    for (y0, y1) in row_bands {
        let mut min_x = w;
        let mut max_x = 0usize;
        let mut any = false;
        for y in y0..=y1 {
            for x in 0..w {
                if mask[y * w + x] {
                    any = true;
                    min_x = min_x.min(x);
                    max_x = max_x.max(x);
                }
            }
        }
        if any {
            boxes.push([min_x as i32, y0 as i32, max_x as i32, y1 as i32]);
        }
    }
    boxes
}

pub fn infer_bg_and_size(path: &Path) -> Result<(u32, u32, String), String> {
    let img = image::open(path).map_err(|e| e.to_string())?.to_rgba8();
    let w = img.width() as usize;
    let h = img.height() as usize;
    let raw = img.as_raw();
    let total = w * h;
    let trans_cnt = (0..total).filter(|&i| raw[i * 4 + 3] == 0).count();
    if (trans_cnt as f32 / total.max(1) as f32) > 0.05 {
        return Ok((w as u32, h as u32, "#00000000".into()));
    }
    let cw = 10.min(w);
    let ch = 10.min(h);
    let mut bg = [0u8; 4];
    bg[3] = 255;
    for c in 0..3 {
        let mut vals = Vec::new();
        for &(bx, by) in &[(0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch)] {
            for y in by..by + ch {
                for x in bx..bx + cw {
                    vals.push(raw[(y * w + x) * 4 + c]);
                }
            }
        }
        vals.sort_unstable();
        bg[c] = vals[vals.len() / 2];
    }
    Ok((w as u32, h as u32, rgba_to_hex_rgba(bg)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hex_to_rgba() {
        assert_eq!(
            hex_to_rgba("#112233", [0, 0, 0, 255]),
            [0x11, 0x22, 0x33, 255]
        );
        assert_eq!(
            hex_to_rgba("#11223380", [0, 0, 0, 255]),
            [0x11, 0x22, 0x33, 0x80]
        );
        assert_eq!(hex_to_rgba("transparent", [0, 0, 0, 255]), [0, 0, 0, 0]);
    }

    #[test]
    fn test_parse_spans() {
        let spans = parse_spans("鬼[r]隐[/r]篇", [255, 255, 255, 255]);
        assert_eq!(spans.len(), 3);
        assert_eq!(spans[0].0, "鬼");
        assert_eq!(spans[1], ("隐".to_string(), [255, 0, 0, 255]));
        assert_eq!(spans[2].0, "篇");
    }

    #[test]
    fn test_detect_line_boxes() {
        let mut img = RgbaImage::from_pixel(100, 60, Rgba([0, 0, 0, 255]));
        for y in 10..20 {
            for x in 15..85 {
                img.put_pixel(x, y, Rgba([255, 255, 255, 255]));
            }
        }
        for y in 35..45 {
            for x in 20..70 {
                img.put_pixel(x, y, Rgba([255, 255, 255, 255]));
            }
        }
        let boxes = detect_line_boxes(&img);
        assert_eq!(boxes, vec![[15, 10, 84, 19], [20, 35, 69, 44]]);
    }
}
