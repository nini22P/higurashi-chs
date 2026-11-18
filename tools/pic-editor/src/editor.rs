use crate::model::{hex_to_rgba, rgba_to_hex_rgb, Align, PicConfig, PicItem, TextBlock, Valign};
use crate::render::{
    detect_line_boxes, infer_bg_and_size, rects_overlap, render_block_layer, render_item, FontCache,
};
use eframe::egui;
use image::RgbaImage;
use rayon::prelude::*;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};

const MAX_TILE_H: u32 = 2048;

#[derive(Clone, Copy, PartialEq, Eq)]
enum ViewMode {
    VStack,
    HStack,
    Rendered,
    Orig,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum FilterMode {
    All,
    WithBlocks,
    NoBlocks,
}

#[derive(Clone)]
struct CopiedStyle {
    x: i32,
    y: i32,
    font: String,
    font_size: u32,
    line_gap: i32,
    blank_height: i32,
    char_gap: i32,
    scale_x: f32,
    align: Align,
    valign: Valign,
    color: String,
}

#[derive(Clone, PartialEq)]
struct BlockVisualKey {
    translation: String,
    font: String,
    font_size: u32,
    line_gap: i32,
    char_gap: i32,
    blank_height: i32,
    scale_x_bits: u32,
    align: Align,
    color: String,
}

impl BlockVisualKey {
    fn from_block(b: &TextBlock) -> Self {
        Self {
            translation: b.translation.clone(),
            font: b.font.clone(),
            font_size: b.font_size,
            line_gap: b.line_gap,
            char_gap: b.char_gap,
            blank_height: b.blank_height,
            scale_x_bits: b.scale_x.to_bits(),
            align: b.align.clone(),
            color: b.color.clone(),
        }
    }
}

struct CachedBlockTex {
    key: BlockVisualKey,
    tex: Option<egui::TextureHandle>,
    size: [u32; 2],
}

struct TiledTexture {
    width: u32,
    height: u32,
    tiles: Vec<(u32, u32, egui::TextureHandle)>,
}

impl TiledTexture {
    fn from_rgba(ctx: &egui::Context, prefix: &str, rgba: &RgbaImage) -> Self {
        let w = rgba.width();
        let h = rgba.height();
        let raw = rgba.as_raw();
        let stride = w as usize * 4;
        let mut tiles = Vec::new();
        let mut y0 = 0u32;
        while y0 < h {
            let th = (h - y0).min(MAX_TILE_H);
            let start = y0 as usize * stride;
            let end = (y0 + th) as usize * stride;
            let cimg = egui::ColorImage::from_rgba_unmultiplied(
                [w as usize, th as usize],
                &raw[start..end],
            );
            let tex = ctx.load_texture(
                format!("{prefix}:tile_{y0}"),
                cimg,
                egui::TextureOptions::LINEAR,
            );
            tiles.push((y0, th, tex));
            y0 += th;
        }
        Self {
            width: w,
            height: h,
            tiles,
        }
    }

    fn draw(
        &self,
        painter: &egui::Painter,
        img_rect: egui::Rect,
        clip_rect: egui::Rect,
        scale: f32,
    ) {
        let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
        for (y0, th, tex) in &self.tiles {
            let min_y = img_rect.min.y + *y0 as f32 * scale;
            let max_y = min_y + *th as f32 * scale;
            if max_y < clip_rect.min.y || min_y > clip_rect.max.y {
                continue;
            }
            let tile_rect = egui::Rect::from_min_max(
                egui::pos2(img_rect.min.x, min_y),
                egui::pos2(img_rect.max.x, max_y),
            );
            painter.image(tex.id(), tile_rect, uv, egui::Color32::WHITE);
        }
    }
}

pub struct PicEditorApp {
    json_path: String,
    orig_dir: String,
    font_dir: String,
    out_dir: String,

    fonts_map: BTreeMap<String, String>,
    items: Vec<PicItem>,
    committed_items: Vec<PicItem>,
    undo_stack: Vec<Vec<PicItem>>,
    redo_stack: Vec<Vec<PicItem>>,
    in_edit_gesture: bool,
    last_text_edit_time: Option<f64>,
    font_cache: FontCache,

    search: String,
    filter: FilterMode,
    current_idx: Option<usize>,
    current_block_idx: usize,

    view_mode: ViewMode,
    show_box: bool,
    zoom_fit: bool,
    zoom: f32,
    pan: egui::Vec2,

    orig_rgba: Option<(String, RgbaImage)>,
    orig_tex: Option<(String, TiledTexture)>,
    orig_boxes: Vec<[i32; 4]>,
    checker_tex: Option<egui::TextureHandle>,

    block_cache: Vec<CachedBlockTex>,
    ren_rects: Vec<[i32; 4]>,
    ren_panel_rect: Option<egui::Rect>,

    block_selected: bool,
    dragging_block: Option<(f32, f32, i32, i32)>,
    dragging_hscroll: bool,
    dragging_vscroll: bool,
    last_canvas_rect: Option<egui::Rect>,
    copied_style: Option<CopiedStyle>,

    needs_rerender: bool,
    dirty: bool,
    status: String,
}

impl PicEditorApp {
    pub fn new(
        cc: &eframe::CreationContext<'_>,
        json_path: String,
        orig_dir: String,
        font_dir: String,
        out_dir: String,
    ) -> Self {
        setup_cjk_fonts(&cc.egui_ctx);
        let mut app = Self {
            json_path,
            orig_dir,
            font_dir,
            out_dir,
            fonts_map: BTreeMap::new(),
            items: Vec::new(),
            committed_items: Vec::new(),
            undo_stack: Vec::new(),
            redo_stack: Vec::new(),
            in_edit_gesture: false,
            last_text_edit_time: None,
            font_cache: FontCache::default(),
            search: String::new(),
            filter: FilterMode::All,
            current_idx: None,
            current_block_idx: 0,
            view_mode: ViewMode::VStack,
            show_box: true,
            zoom_fit: true,
            zoom: 1.0,
            pan: egui::Vec2::ZERO,
            orig_rgba: None,
            orig_tex: None,
            orig_boxes: Vec::new(),
            checker_tex: None,
            block_cache: Vec::new(),
            ren_rects: Vec::new(),
            ren_panel_rect: None,
            block_selected: false,
            dragging_block: None,
            dragging_hscroll: false,
            dragging_vscroll: false,
            last_canvas_rect: None,
            copied_style: None,
            needs_rerender: false,
            dirty: false,
            status: String::new(),
        };
        if !app.json_path.trim().is_empty() {
            app.load_json();
        } else if !app.orig_dir.trim().is_empty() {
            app.merge_orig_files();
        }
        app
    }

    fn record_undo_before_edit(&mut self) {
        if !self.in_edit_gesture {
            self.undo_stack.push(self.committed_items.clone());
            if self.undo_stack.len() > 100 {
                self.undo_stack.remove(0);
            }
            self.redo_stack.clear();
            self.in_edit_gesture = true;
        }
    }

    fn commit_discrete_edit(&mut self) {
        self.committed_items = self.items.clone();
        self.in_edit_gesture = false;
    }

    fn undo(&mut self) {
        if let Some(prev) = self.undo_stack.pop() {
            self.redo_stack.push(self.items.clone());
            self.items = prev;
            self.committed_items = self.items.clone();
            self.in_edit_gesture = false;
            if let Some(idx) = self.current_idx {
                if idx < self.items.len() && !self.items[idx].blocks.is_empty() {
                    self.current_block_idx =
                        self.current_block_idx.min(self.items[idx].blocks.len() - 1);
                } else {
                    self.current_block_idx = 0;
                }
            }
            self.dirty = true;
            self.needs_rerender = true;
            self.status = "已撤销".into();
        }
    }

    fn redo(&mut self) {
        if let Some(next) = self.redo_stack.pop() {
            self.undo_stack.push(self.items.clone());
            self.items = next;
            self.committed_items = self.items.clone();
            self.in_edit_gesture = false;
            if let Some(idx) = self.current_idx {
                if idx < self.items.len() && !self.items[idx].blocks.is_empty() {
                    self.current_block_idx =
                        self.current_block_idx.min(self.items[idx].blocks.len() - 1);
                } else {
                    self.current_block_idx = 0;
                }
            }
            self.dirty = true;
            self.needs_rerender = true;
            self.status = "已重做".into();
        }
    }

    fn load_json(&mut self) {
        let p = PathBuf::from(self.json_path.trim());
        match std::fs::read_to_string(&p) {
            Ok(txt) => match serde_json::from_str::<PicConfig>(&txt) {
                Ok(cfg) => {
                    self.fonts_map = cfg.fonts;
                    self.items = cfg.items;
                    self.dirty = false;
                    self.current_idx = None;
                    self.orig_rgba = None;
                    self.orig_tex = None;
                    self.block_cache.clear();
                    self.merge_orig_files();
                    self.committed_items = self.items.clone();
                    self.undo_stack.clear();
                    self.redo_stack.clear();
                    self.in_edit_gesture = false;
                    self.status = format!("已加载 {}", p.display());
                }
                Err(e) => self.status = format!("JSON 解析失败: {e}"),
            },
            Err(e) => self.status = format!("读取失败: {e}"),
        }
    }

    fn merge_orig_files(&mut self) {
        let mut by_file: HashMap<String, PicItem> = self
            .items
            .drain(..)
            .map(|it| (it.file.clone(), it))
            .collect();
        let mut merged = Vec::new();
        let mut seen = HashSet::new();

        let orig_root = PathBuf::from(self.orig_dir.trim());
        if !self.orig_dir.trim().is_empty() && orig_root.is_dir() {
            let mut pngs = Vec::new();
            collect_pngs(&orig_root, &orig_root, &mut pngs);
            pngs.sort();
            for rel in pngs {
                seen.insert(rel.clone());
                if let Some(it) = by_file.remove(&rel) {
                    merged.push(it);
                } else {
                    merged.push(PicItem {
                        file: rel,
                        width: 0,
                        height: 0,
                        bg_color: "#000000FF".into(),
                        blocks: Vec::new(),
                    });
                }
            }
        }
        let mut leftovers: Vec<PicItem> = by_file
            .into_values()
            .filter(|it| !seen.contains(&it.file))
            .collect();
        leftovers.sort_by(|a, b| a.file.cmp(&b.file));
        merged.extend(leftovers);

        self.items = merged;
        self.committed_items = self.items.clone();
        if !self.items.is_empty() && self.current_idx.is_none() {
            self.select_item(0);
        }
    }

    fn select_item(&mut self, idx: usize) {
        if idx >= self.items.len() {
            return;
        }
        self.current_idx = Some(idx);
        self.current_block_idx = 0;
        self.block_selected = false;
        self.dragging_block = None;
        self.orig_rgba = None;
        self.orig_tex = None;
        self.orig_boxes.clear();
        self.block_cache.clear();
        self.ren_rects.clear();
        self.zoom_fit = true;

        if self.items[idx].width == 0 && !self.orig_dir.trim().is_empty() {
            let op = Path::new(self.orig_dir.trim()).join(&self.items[idx].file);
            if op.is_file() {
                if let Ok((w, h, bg)) = infer_bg_and_size(&op) {
                    self.items[idx].width = w;
                    self.items[idx].height = h;
                    self.items[idx].bg_color = bg;
                    self.committed_items[idx].width = w;
                    self.committed_items[idx].height = h;
                    self.committed_items[idx].bg_color = self.items[idx].bg_color.clone();
                }
            }
        }
        self.needs_rerender = true;
    }

    fn save_json(&mut self) {
        if self.json_path.trim().is_empty() {
            self.status = "请先选择 JSON 路径".into();
            return;
        }
        let kept: Vec<PicItem> = self
            .items
            .iter()
            .filter(|it| !it.blocks.is_empty())
            .cloned()
            .collect();
        let cfg = PicConfig {
            fonts: self.fonts_map.clone(),
            items: kept,
        };
        match serde_json::to_string_pretty(&cfg) {
            Ok(s) => match std::fs::write(self.json_path.trim(), s) {
                Ok(_) => {
                    self.dirty = false;
                    self.status = format!("已保存 ({})", cfg.items.len());
                }
                Err(e) => self.status = format!("保存失败: {e}"),
            },
            Err(e) => self.status = format!("序列化失败: {e}"),
        }
    }

    fn export_current(&mut self) {
        let Some(idx) = self.current_idx else { return };
        if self.out_dir.trim().is_empty() {
            self.status = "请先选择输出目录".into();
            return;
        }
        let it = &self.items[idx];
        let orig_ref =
            self.orig_rgba
                .as_ref()
                .and_then(|(f, im)| if *f == it.file { Some(im) } else { None });
        match render_item(
            it,
            &self.fonts_map,
            self.font_dir.trim(),
            orig_ref,
            Some(&self.orig_boxes),
            &self.font_cache,
        ) {
            Ok((img, _)) => {
                let dst = Path::new(self.out_dir.trim()).join(&it.file);
                if let Some(parent) = dst.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                match img.save(&dst) {
                    Ok(_) => self.status = format!("已导出: {}", dst.display()),
                    Err(e) => self.status = format!("导出失败: {e}"),
                }
            }
            Err(e) => self.status = format!("渲染错误: {e}"),
        }
    }

    fn export_all(&mut self) {
        if self.out_dir.trim().is_empty() {
            self.status = "请先选择输出目录".into();
            return;
        }
        let out_dir = PathBuf::from(self.out_dir.trim());
        let orig_root = PathBuf::from(self.orig_dir.trim());
        let has_orig_dir = !self.orig_dir.trim().is_empty() && orig_root.is_dir();

        let active: Vec<&PicItem> = self
            .items
            .iter()
            .filter(|it| {
                !it.blocks.is_empty() && it.blocks.iter().any(|b| !b.translation.trim().is_empty())
            })
            .collect();
        let skipped = self.items.len() - active.len();

        let results: Vec<Result<(), String>> = active
            .par_iter()
            .map(|it| {
                let loaded_orig = if has_orig_dir {
                    let op = orig_root.join(&it.file);
                    image::open(&op).ok().map(|im| im.to_rgba8())
                } else {
                    None
                };
                let (img, _) = render_item(
                    it,
                    &self.fonts_map,
                    self.font_dir.trim(),
                    loaded_orig.as_ref(),
                    None,
                    &self.font_cache,
                )?;
                let dst = out_dir.join(&it.file);
                if let Some(parent) = dst.parent() {
                    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                img.save(&dst).map_err(|e| e.to_string())
            })
            .collect();

        let mut errs = 0usize;
        let mut first_err = String::new();
        for r in results {
            if let Err(e) = r {
                errs += 1;
                if first_err.is_empty() {
                    first_err = e;
                }
            }
        }
        if errs == 0 {
            self.status = format!("批量导出完成: 成功 {}, 跳过 {}", active.len(), skipped);
        } else {
            self.status = format!("导出完成但有 {errs} 个错误: {first_err}");
        }
    }

    fn ensure_textures(&mut self, ctx: &egui::Context) {
        if self.checker_tex.is_none() {
            let tile = [
                egui::Color32::from_gray(220),
                egui::Color32::from_gray(185),
                egui::Color32::from_gray(185),
                egui::Color32::from_gray(220),
            ];
            let cimg = egui::ColorImage::new([2, 2], tile.to_vec());
            let opts = egui::TextureOptions {
                magnification: egui::TextureFilter::Nearest,
                minification: egui::TextureFilter::Nearest,
                wrap_mode: egui::TextureWrapMode::Repeat,
                mipmap_mode: None,
            };
            self.checker_tex = Some(ctx.load_texture("checker_tile", cimg, opts));
        }

        let Some(idx) = self.current_idx else { return };
        let file = self.items[idx].file.clone();

        if self.orig_tex.as_ref().map(|t| t.0 != file).unwrap_or(true)
            && !self.orig_dir.trim().is_empty()
        {
            let op = Path::new(self.orig_dir.trim()).join(&file);
            if op.is_file() {
                if let Ok(dyn_im) = image::open(&op) {
                    let rgba = dyn_im.to_rgba8();
                    self.orig_boxes = detect_line_boxes(&rgba);
                    let tiled = TiledTexture::from_rgba(ctx, &format!("orig:{file}"), &rgba);
                    self.orig_rgba = Some((file.clone(), rgba));
                    self.orig_tex = Some((file.clone(), tiled));
                }
            }
        }

        if self.needs_rerender {
            self.needs_rerender = false;
            let it = &self.items[idx];
            let mut new_cache = Vec::with_capacity(it.blocks.len());
            let mut rects = Vec::with_capacity(it.blocks.len());
            let mut err_msg = None;

            for (bi, b) in it.blocks.iter().enumerate() {
                let key = BlockVisualKey::from_block(b);
                let reused = self
                    .block_cache
                    .get(bi)
                    .filter(|c| c.key == key)
                    .map(|c| (c.tex.clone(), c.size));

                let (tex_opt, size) = if let Some((t, sz)) = reused {
                    (t, sz)
                } else {
                    match render_block_layer(
                        b,
                        &self.fonts_map,
                        self.font_dir.trim(),
                        &self.font_cache,
                    ) {
                        Ok((Some(layer), _)) => {
                            let sz = [layer.width(), layer.height()];
                            let cimg = egui::ColorImage::from_rgba_unmultiplied(
                                [sz[0] as usize, sz[1] as usize],
                                layer.as_raw(),
                            );
                            let tex = ctx.load_texture(
                                format!("blk:{file}:{bi}"),
                                cimg,
                                egui::TextureOptions::LINEAR,
                            );
                            (Some(tex), sz)
                        }
                        Ok((None, _)) => (None, [0, 0]),
                        Err(e) => {
                            err_msg = Some(e);
                            (None, [0, 0])
                        }
                    }
                };

                let rect = if tex_opt.is_some() {
                    let cw = size[0] as i32;
                    let ch = size[1] as i32;
                    let ox = match b.align {
                        Align::Center => b.x - cw / 2,
                        Align::Left => b.x,
                        Align::Right => b.x - cw,
                    };
                    let oy = match b.valign {
                        Valign::Middle => b.y - ch / 2,
                        Valign::Top => b.y,
                        Valign::Bottom => b.y - ch,
                    };
                    [ox, oy, ox + cw, oy + ch]
                } else {
                    [b.x - 20, b.y - 20, b.x + 20, b.y + 20]
                };

                rects.push(rect);
                new_cache.push(CachedBlockTex {
                    key,
                    tex: tex_opt,
                    size,
                });
            }

            self.block_cache = new_cache;
            self.ren_rects = rects;

            if let Some(e) = err_msg {
                self.status = format!("渲染错误: {e}");
            } else {
                self.status = format!(
                    "{} | {}行{}",
                    it.file,
                    self.orig_boxes.len(),
                    if self.dirty { " | 未保存" } else { "" }
                );
            }
        }
    }
}

impl eframe::App for PicEditorApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();

        let now = ctx.input(|i| i.time);
        if self.in_edit_gesture {
            let pointer_idle =
                !ctx.input(|i| i.pointer.any_down()) && !ctx.egui_wants_keyboard_input();
            let typing_idle = self
                .last_text_edit_time
                .map(|t| now - t > 0.6)
                .unwrap_or(false);
            if pointer_idle || typing_idle {
                self.committed_items = self.items.clone();
                self.in_edit_gesture = false;
                self.last_text_edit_time = None;
            }
        }

        if ctx.input_mut(|i| i.consume_key(egui::Modifiers::CTRL, egui::Key::S)) {
            self.save_json();
        }
        if ctx.input_mut(|i| i.consume_key(egui::Modifiers::CTRL, egui::Key::Z)) {
            self.undo();
        }
        if ctx.input_mut(|i| {
            i.consume_key(egui::Modifiers::CTRL, egui::Key::Y)
                || i.consume_key(egui::Modifiers::CTRL | egui::Modifiers::SHIFT, egui::Key::Z)
        }) {
            self.redo();
        }

        if self.block_selected && !ctx.egui_wants_keyboard_input() {
            let (dx, dy) = ctx.input(|i| {
                let step = if i.modifiers.shift { 10 } else { 1 };
                let mut dx = 0;
                let mut dy = 0;
                if i.key_pressed(egui::Key::ArrowLeft) {
                    dx -= step;
                }
                if i.key_pressed(egui::Key::ArrowRight) {
                    dx += step;
                }
                if i.key_pressed(egui::Key::ArrowUp) {
                    dy -= step;
                }
                if i.key_pressed(egui::Key::ArrowDown) {
                    dy += step;
                }
                (dx, dy)
            });
            if dx != 0 || dy != 0 {
                self.record_undo_before_edit();
                if let Some(idx) = self.current_idx {
                    if let Some(b) = self.items[idx].blocks.get_mut(self.current_block_idx) {
                        b.x += dx;
                        b.y += dy;
                        self.dirty = true;
                        self.needs_rerender = true;
                    }
                }
                self.commit_discrete_edit();
            }
        }

        self.ensure_textures(&ctx);

        // Top Path Bar
        egui::Panel::top("top_bar").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label("JSON:");
                ui.add(egui::TextEdit::singleline(&mut self.json_path).desired_width(180.0));
                if ui.button("浏览").clicked() {
                    if let Some(p) = rfd::FileDialog::new()
                        .add_filter("JSON", &["json"])
                        .pick_file()
                    {
                        self.json_path = p.display().to_string();
                        self.load_json();
                    }
                }
                if ui.button("加载").clicked() {
                    self.load_json();
                }

                ui.separator();
                ui.label("原图目录:");
                ui.add(egui::TextEdit::singleline(&mut self.orig_dir).desired_width(160.0));
                if ui.button("浏览").clicked() {
                    if let Some(p) = rfd::FileDialog::new().pick_folder() {
                        self.orig_dir = p.display().to_string();
                        self.orig_rgba = None;
                        self.orig_tex = None;
                        self.merge_orig_files();
                    }
                }

                ui.separator();
                ui.label("字体目录:");
                ui.add(egui::TextEdit::singleline(&mut self.font_dir).desired_width(140.0));
                if ui.button("浏览").clicked() {
                    if let Some(p) = rfd::FileDialog::new().pick_folder() {
                        self.font_dir = p.display().to_string();
                        self.block_cache.clear();
                        self.needs_rerender = true;
                    }
                }

                ui.separator();
                ui.label("输出目录:");
                ui.add(egui::TextEdit::singleline(&mut self.out_dir).desired_width(140.0));
                if ui.button("浏览").clicked() {
                    if let Some(p) = rfd::FileDialog::new().pick_folder() {
                        self.out_dir = p.display().to_string();
                    }
                }
            });
        });

        // Bottom Status Bar
        egui::Panel::bottom("status_bar").show(ui, |ui| {
            ui.label(&self.status);
        });

        // Left Sidebar
        egui::Panel::left("left_panel")
            .default_size(240.0)
            .resizable(true)
            .show(ui, |ui| {
                ui.add(
                    egui::TextEdit::singleline(&mut self.search)
                        .hint_text("搜索文件名...")
                        .desired_width(f32::INFINITY),
                );
                egui::ComboBox::from_id_salt("filter_cb")
                    .selected_text(match self.filter {
                        FilterMode::All => "All",
                        FilterMode::WithBlocks => "With-blocks",
                        FilterMode::NoBlocks => "No-blocks",
                    })
                    .width(ui.available_width())
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.filter, FilterMode::All, "All");
                        ui.selectable_value(
                            &mut self.filter,
                            FilterMode::WithBlocks,
                            "With-blocks",
                        );
                        ui.selectable_value(&mut self.filter, FilterMode::NoBlocks, "No-blocks");
                    });
                ui.separator();

                let q = self.search.trim().to_lowercase();
                let mut next_select = None;
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for (idx, it) in self.items.iter().enumerate() {
                            if !q.is_empty() && !it.file.to_lowercase().contains(&q) {
                                continue;
                            }
                            let bc = it.blocks.len();
                            match self.filter {
                                FilterMode::All => {}
                                FilterMode::WithBlocks if bc == 0 => continue,
                                FilterMode::NoBlocks if bc > 0 => continue,
                                _ => {}
                            }
                            let selected = self.current_idx == Some(idx);
                            if ui.selectable_label(selected, &it.file).clicked() {
                                next_select = Some(idx);
                            }
                        }
                    });
                if let Some(idx) = next_select {
                    self.select_item(idx);
                }
            });

        // Right Properties Panel
        egui::Panel::right("right_panel")
            .default_size(340.0)
            .min_size(320.0)
            .resizable(true)
            .show(ui, |ui| {
                self.draw_right_panel(ui);
            });

        // Center Preview Panel
        egui::CentralPanel::default().show(ui, |ui| {
            self.draw_center_panel(ui);
        });
    }
}

impl PicEditorApp {
    fn draw_right_panel(&mut self, ui: &mut egui::Ui) {
        let Some(idx) = self.current_idx else {
            ui.label("未选择图片");
            return;
        };

        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.set_min_width(ui.available_width());
                ui.horizontal(|ui| {
                    ui.label("背景色:");
                    let mut bg_val = self.items[idx].bg_color.clone();
                    if ui
                        .add(egui::TextEdit::singleline(&mut bg_val).desired_width(90.0))
                        .changed()
                    {
                        self.record_undo_before_edit();
                        self.items[idx].bg_color = bg_val;
                        self.dirty = true;
                        self.needs_rerender = true;
                    }
                });

                ui.horizontal(|ui| {
                    ui.label("文本块:");
                    let blocks_len = self.items[idx].blocks.len();
                    let sel_text = if blocks_len > 0 {
                        let bi = self.current_block_idx.min(blocks_len - 1);
                        format!("{}: {}", bi + 1, self.items[idx].blocks[bi].name)
                    } else {
                        "无".into()
                    };
                    egui::ComboBox::from_id_salt("block_cb")
                        .selected_text(sel_text)
                        .width(90.0)
                        .show_ui(ui, |ui| {
                            for (bi, b) in self.items[idx].blocks.iter().enumerate() {
                                if ui
                                    .selectable_value(
                                        &mut self.current_block_idx,
                                        bi,
                                        format!("{}: {}", bi + 1, b.name),
                                    )
                                    .clicked()
                                {
                                    self.needs_rerender = true;
                                }
                            }
                        });

                    if ui.button("+").clicked() {
                        self.record_undo_before_edit();
                        let w = self.items[idx].width.max(100) as i32;
                        let h = self.items[idx].height.max(60) as i32;
                        let def_font = self
                            .fonts_map
                            .keys()
                            .next()
                            .cloned()
                            .unwrap_or_else(|| "serif".into());
                        let n = self.items[idx].blocks.len() + 1;
                        self.items[idx].blocks.push(TextBlock {
                            name: format!("block_{n}"),
                            text: String::new(),
                            translation: "新文本块".into(),
                            x: w / 2,
                            y: h / 2,
                            font: def_font,
                            font_size: 48,
                            line_gap: 16,
                            char_gap: 0,
                            blank_height: 36,
                            scale_x: 1.0,
                            align: Align::Center,
                            valign: Valign::Middle,
                            color: "#FFFFFF".into(),
                        });
                        self.current_block_idx = self.items[idx].blocks.len() - 1;
                        self.commit_discrete_edit();
                        self.dirty = true;
                        self.needs_rerender = true;
                    }
                    if ui.button("-").clicked() && !self.items[idx].blocks.is_empty() {
                        self.record_undo_before_edit();
                        self.items[idx].blocks.remove(self.current_block_idx);
                        self.current_block_idx = self.current_block_idx.saturating_sub(1);
                        self.block_selected = false;
                        self.commit_discrete_edit();
                        self.dirty = true;
                        self.needs_rerender = true;
                    }
                });

                ui.horizontal(|ui| {
                    if ui.button("复制样式").clicked() {
                        if let Some(b) = self.items[idx].blocks.get(self.current_block_idx) {
                            self.copied_style = Some(CopiedStyle {
                                x: b.x,
                                y: b.y,
                                font: b.font.clone(),
                                font_size: b.font_size,
                                line_gap: b.line_gap,
                                blank_height: b.blank_height,
                                char_gap: b.char_gap,
                                scale_x: b.scale_x,
                                align: b.align.clone(),
                                valign: b.valign.clone(),
                                color: b.color.clone(),
                            });
                            self.status = "已复制样式".into();
                        }
                    }
                    if ui.button("粘贴样式").clicked() {
                        if let Some(st) = self.copied_style.clone() {
                            self.record_undo_before_edit();
                            if let Some(b) = self.items[idx].blocks.get_mut(self.current_block_idx)
                            {
                                b.x = st.x;
                                b.y = st.y;
                                b.font = st.font;
                                b.font_size = st.font_size;
                                b.line_gap = st.line_gap;
                                b.blank_height = st.blank_height;
                                b.char_gap = st.char_gap;
                                b.scale_x = st.scale_x;
                                b.align = st.align;
                                b.valign = st.valign;
                                b.color = st.color;
                                self.dirty = true;
                                self.needs_rerender = true;
                                self.status = "已粘贴样式".into();
                            }
                            self.commit_discrete_edit();
                        }
                    }
                });

                if self.current_block_idx < self.items[idx].blocks.len() {
                    let item_w = self.items[idx].width as i32;
                    let item_h = self.items[idx].height as i32;
                    let cur_rect = self.ren_rects.get(self.current_block_idx).copied();
                    let orig_boxes_bounds = if !self.orig_boxes.is_empty() {
                        let x0 = self.orig_boxes.iter().map(|r| r[0]).min().unwrap();
                        let y0 = self.orig_boxes.iter().map(|r| r[1]).min().unwrap();
                        let x1 = self.orig_boxes.iter().map(|r| r[2]).max().unwrap();
                        let y1 = self.orig_boxes.iter().map(|r| r[3]).max().unwrap();
                        Some((x0, y0, x1, y1))
                    } else {
                        None
                    };
                    let font_keys: Vec<String> = self.fonts_map.keys().cloned().collect();

                    let mut orig_changed = false;
                    let mut changed = false;
                    let mut discrete = false;

                    let mut block = self.items[idx].blocks[self.current_block_idx].clone();

                    ui.label("原文:");
                    let mut orig_edit = block.text.replace("\\n", "\n");
                    let orig_resp = ui.add(
                        egui::TextEdit::multiline(&mut orig_edit)
                            .desired_rows(3)
                            .desired_width(f32::INFINITY),
                    );
                    if orig_resp.changed() {
                        block.text = orig_edit;
                        orig_changed = true;
                        self.last_text_edit_time = Some(ui.input(|i| i.time));
                    }
                    if orig_resp.lost_focus() && self.in_edit_gesture {
                        discrete = true;
                    }

                    ui.label("译文:");
                    let mut tr_edit = block.translation.replace("\\n", "\n");
                    let tr_resp = ui.add(
                        egui::TextEdit::multiline(&mut tr_edit)
                            .desired_rows(4)
                            .desired_width(f32::INFINITY),
                    );
                    if tr_resp.changed() {
                        block.translation = tr_edit;
                        changed = true;
                        self.last_text_edit_time = Some(ui.input(|i| i.time));
                    }
                    if tr_resp.lost_focus() && self.in_edit_gesture {
                        discrete = true;
                    }

                    ui.separator();
                    ui.horizontal(|ui| {
                        ui.label("字体:");
                        egui::ComboBox::from_id_salt("font_cb")
                            .selected_text(&block.font)
                            .width(120.0)
                            .show_ui(ui, |ui| {
                                for k in &font_keys {
                                    if ui.selectable_value(&mut block.font, k.clone(), k).clicked()
                                    {
                                        changed = true;
                                        discrete = true;
                                    }
                                }
                            });
                    });

                    ui.horizontal(|ui| {
                        ui.label("颜色:");
                        if ui
                            .add(egui::TextEdit::singleline(&mut block.color).desired_width(80.0))
                            .changed()
                        {
                            changed = true;
                        }
                        let rgba = hex_to_rgba(&block.color, [255, 255, 255, 255]);
                        let mut rgb = [rgba[0], rgba[1], rgba[2]];
                        if ui.color_edit_button_srgb(&mut rgb).changed() {
                            block.color = rgba_to_hex_rgb(rgb);
                            changed = true;
                        }
                    });

                    ui.horizontal(|ui| {
                        ui.add_sized([58.0, 18.0], egui::Label::new("字号:"));
                        changed |= ui
                            .add(egui::Slider::new(&mut block.font_size, 8..=2000))
                            .changed();
                    });
                    ui.horizontal(|ui| {
                        ui.add_sized([58.0, 18.0], egui::Label::new("行距:"));
                        changed |= ui
                            .add(egui::Slider::new(&mut block.line_gap, -200..=400))
                            .changed();
                    });
                    ui.horizontal(|ui| {
                        ui.add_sized([58.0, 18.0], egui::Label::new("空行高度:"));
                        changed |= ui
                            .add(egui::Slider::new(&mut block.blank_height, 0..=400))
                            .changed();
                    });
                    ui.horizontal(|ui| {
                        ui.add_sized([58.0, 18.0], egui::Label::new("字间距:"));
                        changed |= ui
                            .add(egui::Slider::new(&mut block.char_gap, -200..=300))
                            .changed();
                    });
                    ui.horizontal(|ui| {
                        ui.add_sized([58.0, 18.0], egui::Label::new("横向缩放:"));
                        changed |= ui
                            .add(egui::Slider::new(&mut block.scale_x, 0.20..=2.50).step_by(0.02))
                            .changed();
                    });

                    ui.horizontal(|ui| {
                        ui.label("水平:");
                        if ui
                            .radio_value(&mut block.align, Align::Left, "left")
                            .changed()
                            || ui
                                .radio_value(&mut block.align, Align::Center, "center")
                                .changed()
                            || ui
                                .radio_value(&mut block.align, Align::Right, "right")
                                .changed()
                        {
                            changed = true;
                            discrete = true;
                        }
                    });
                    ui.horizontal(|ui| {
                        ui.label("垂直:");
                        if ui
                            .radio_value(&mut block.valign, Valign::Top, "top")
                            .changed()
                            || ui
                                .radio_value(&mut block.valign, Valign::Middle, "middle")
                                .changed()
                            || ui
                                .radio_value(&mut block.valign, Valign::Bottom, "bottom")
                                .changed()
                        {
                            changed = true;
                            discrete = true;
                        }
                    });

                    ui.horizontal(|ui| {
                        ui.label("X:");
                        changed |= ui
                            .add(egui::DragValue::new(&mut block.x).speed(1.0))
                            .changed();
                        ui.label("Y:");
                        changed |= ui
                            .add(egui::DragValue::new(&mut block.y).speed(1.0))
                            .changed();
                        if ui.button("对齐原图").clicked() {
                            if let Some((x0, y0, x1, y1)) = orig_boxes_bounds {
                                block.x = match block.align {
                                    Align::Left => x0,
                                    Align::Right => x1,
                                    Align::Center => (x0 + x1) / 2,
                                };
                                block.y = match block.valign {
                                    Valign::Top => y0,
                                    Valign::Bottom => y1,
                                    Valign::Middle => (y0 + y1) / 2,
                                };
                                changed = true;
                                discrete = true;
                            }
                        }
                    });

                    ui.horizontal(|ui| {
                        if ui.button("横向居中").clicked() {
                            if block.align != Align::Center {
                                if let Some([rx0, _, rx1, _]) = cur_rect {
                                    let dx = item_w as f32 / 2.0 - (rx0 + rx1) as f32 / 2.0;
                                    block.x = (block.x as f32 + dx).round() as i32;
                                } else {
                                    block.x = item_w / 2;
                                }
                            } else {
                                block.x = item_w / 2;
                            }
                            changed = true;
                            discrete = true;
                        }
                        if ui.button("竖向居中").clicked() {
                            if block.valign != Valign::Middle {
                                if let Some([_, ry0, _, ry1]) = cur_rect {
                                    let dy = item_h as f32 / 2.0 - (ry0 + ry1) as f32 / 2.0;
                                    block.y = (block.y as f32 + dy).round() as i32;
                                } else {
                                    block.y = item_h / 2;
                                }
                            } else {
                                block.y = item_h / 2;
                            }
                            changed = true;
                            discrete = true;
                        }
                    });

                    if orig_changed || changed {
                        self.record_undo_before_edit();
                        self.items[idx].blocks[self.current_block_idx] = block;
                        self.dirty = true;
                        if changed {
                            self.needs_rerender = true;
                        }
                        if discrete {
                            self.commit_discrete_edit();
                        }
                    }
                }

                ui.separator();
                ui.horizontal(|ui| {
                    if ui.button("保存").clicked() {
                        self.save_json();
                    }
                    if ui.button("导出当前").clicked() {
                        self.export_current();
                    }
                    if ui.button("全部导出").clicked() {
                        self.export_all();
                    }
                });
            });
    }

    fn apply_zoom(&mut self, new_scale: f32, pivot_local: egui::Vec2) {
        let old_scale = self.zoom.max(0.01);
        let clamped = new_scale.clamp(0.1, 8.0);
        self.zoom_fit = false;
        self.zoom = clamped;
        self.pan = pivot_local - (pivot_local - self.pan) * (clamped / old_scale);
    }

    fn draw_center_panel(&mut self, ui: &mut egui::Ui) {
        let center_pivot = self
            .last_canvas_rect
            .map(|r| r.size() * 0.5)
            .unwrap_or(egui::vec2(400.0, 300.0));

        ui.horizontal(|ui| {
            ui.radio_value(&mut self.view_mode, ViewMode::VStack, "上下对比");
            ui.radio_value(&mut self.view_mode, ViewMode::HStack, "左右对比");
            ui.radio_value(&mut self.view_mode, ViewMode::Rendered, "仅渲染图");
            ui.radio_value(&mut self.view_mode, ViewMode::Orig, "仅原图");
            ui.checkbox(&mut self.show_box, "显示 Box");
            ui.separator();
            if ui.button("适应").clicked() {
                self.zoom_fit = true;
                self.pan = egui::Vec2::ZERO;
            }
            if ui.button("-").clicked() {
                self.apply_zoom(self.zoom * 0.85, center_pivot);
            }
            let zlbl = if self.zoom_fit {
                "适应".to_string()
            } else {
                format!("{}%", (self.zoom * 100.0).round() as i32)
            };
            ui.label(zlbl);
            if ui.button("+").clicked() {
                self.apply_zoom(self.zoom * 1.18, center_pivot);
            }
            if ui.button("100%").clicked() {
                self.apply_zoom(1.0, center_pivot);
            }
            ui.separator();
            if ui
                .add_enabled(!self.undo_stack.is_empty(), egui::Button::new("撤销"))
                .clicked()
            {
                self.undo();
            }
            if ui
                .add_enabled(!self.redo_stack.is_empty(), egui::Button::new("重做"))
                .clicked()
            {
                self.redo();
            }
        });
        ui.separator();

        let avail = ui.available_size();
        let (rect, response) = ui.allocate_exact_size(avail, egui::Sense::click_and_drag());
        self.last_canvas_rect = Some(rect);
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, 0.0, egui::Color32::from_rgb(43, 43, 43));

        let Some(idx) = self.current_idx else { return };
        let item_w = self.items[idx].width;
        let item_h = self.items[idx].height;

        let mut panel_kinds: Vec<(&str, [u32; 2], bool)> = Vec::new();
        if matches!(
            self.view_mode,
            ViewMode::VStack | ViewMode::HStack | ViewMode::Orig
        ) {
            if let Some((_, tiled)) = &self.orig_tex {
                panel_kinds.push(("原图", [tiled.width, tiled.height], false));
            }
        }
        if matches!(
            self.view_mode,
            ViewMode::VStack | ViewMode::HStack | ViewMode::Rendered
        ) && item_w > 0
            && item_h > 0
        {
            panel_kinds.push(("渲染预览", [item_w, item_h], true));
        }
        if panel_kinds.is_empty() {
            return;
        }

        let is_hstack = self.view_mode == ViewMode::HStack && panel_kinds.len() == 2;
        let max_pw = panel_kinds.iter().map(|p| p.1[0]).max().unwrap_or(1) as f32;
        let max_ph = panel_kinds.iter().map(|p| p.1[1]).max().unwrap_or(1) as f32;
        let scale = if self.zoom_fit {
            let (slot_w, slot_h) = if is_hstack {
                (
                    ((rect.width() - 28.0) / 2.0 - 16.0).max(80.0),
                    (rect.height() - 52.0).max(60.0),
                )
            } else {
                (
                    (rect.width() - 28.0).max(80.0),
                    ((rect.height() - 28.0) / panel_kinds.len() as f32 - 24.0).max(60.0),
                )
            };
            let s = (slot_w / max_pw).min(slot_h / max_ph).min(2.0);
            self.zoom = s;
            self.pan = egui::Vec2::ZERO;
            s
        } else {
            self.zoom
        };

        if response.hovered() {
            let scroll = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll.abs() > 0.1 {
                let factor = 1.0012f32.powf(scroll);
                let pivot = ui
                    .input(|i| i.pointer.hover_pos())
                    .map(|p| p - rect.min)
                    .unwrap_or_else(|| rect.size() * 0.5);
                self.apply_zoom(scale * factor, pivot);
            }
        }
        let scale = self.zoom;

        let content_w = if is_hstack {
            panel_kinds
                .iter()
                .map(|p| p.1[0] as f32 * scale)
                .sum::<f32>()
                + 48.0
        } else {
            max_pw * scale + 28.0
        };
        let content_h = if is_hstack {
            max_ph * scale + 44.0
        } else {
            panel_kinds
                .iter()
                .map(|p| p.1[1] as f32 * scale + 30.0)
                .sum::<f32>()
                + 16.0
        };
        let sb_size = 12.0;
        let has_h = !self.zoom_fit && content_w > rect.width();
        let has_v = !self.zoom_fit && content_h > rect.height();

        let h_track = egui::Rect::from_min_max(
            egui::pos2(rect.min.x + 2.0, rect.max.y - sb_size),
            egui::pos2(
                rect.max.x - if has_v { sb_size + 2.0 } else { 2.0 },
                rect.max.y - 2.0,
            ),
        );
        let v_track = egui::Rect::from_min_max(
            egui::pos2(rect.max.x - sb_size, rect.min.y + 2.0),
            egui::pos2(
                rect.max.x - 2.0,
                rect.max.y - if has_h { sb_size + 2.0 } else { 2.0 },
            ),
        );

        if response.drag_started_by(egui::PointerButton::Primary) || response.clicked() {
            if let Some(pointer) = ui.input(|i| i.pointer.interact_pos()) {
                if has_h && h_track.contains(pointer) {
                    self.dragging_hscroll = true;
                } else if has_v && v_track.contains(pointer) {
                    self.dragging_vscroll = true;
                } else if let Some(rrect) = self.ren_panel_rect {
                    let px = (pointer.x - rrect.min.x) / scale;
                    let py = (pointer.y - rrect.min.y) / scale;
                    let mut hit = None;
                    for (bi, &[rx0, ry0, rx1, ry1]) in self.ren_rects.iter().enumerate() {
                        if px >= (rx0 - 8) as f32
                            && px <= (rx1 + 8) as f32
                            && py >= (ry0 - 8) as f32
                            && py <= (ry1 + 8) as f32
                        {
                            hit = Some(bi);
                            break;
                        }
                    }
                    if hit.is_none() {
                        for (bi, b) in self.items[idx].blocks.iter().enumerate() {
                            if (px - b.x as f32).abs() <= 20.0 && (py - b.y as f32).abs() <= 20.0 {
                                hit = Some(bi);
                                break;
                            }
                        }
                    }
                    if let Some(bi) = hit {
                        self.block_selected = true;
                        self.current_block_idx = bi;
                        let b = &self.items[idx].blocks[bi];
                        self.dragging_block = Some((px, py, b.x, b.y));
                    } else {
                        self.block_selected = false;
                        self.dragging_block = None;
                    }
                }
            }
        }

        if response.dragged_by(egui::PointerButton::Primary) {
            if self.dragging_hscroll {
                let delta = response.drag_delta().x;
                let max_pan_x = (content_w - rect.width()).max(1.0);
                self.pan.x -= delta * (content_w / h_track.width().max(1.0));
                self.pan.x = self.pan.x.clamp(-max_pan_x, 0.0);
            } else if self.dragging_vscroll {
                let delta = response.drag_delta().y;
                let max_pan_y = (content_h - rect.height()).max(1.0);
                self.pan.y -= delta * (content_h / v_track.height().max(1.0));
                self.pan.y = self.pan.y.clamp(-max_pan_y, 0.0);
            } else if let Some((spx, spy, ox, oy)) = self.dragging_block {
                if let (Some(pointer), Some(rrect)) =
                    (ui.input(|i| i.pointer.interact_pos()), self.ren_panel_rect)
                {
                    let px = (pointer.x - rrect.min.x) / scale;
                    let py = (pointer.y - rrect.min.y) / scale;
                    let nx = ox + (px - spx).round() as i32;
                    let ny = oy + (py - spy).round() as i32;
                    let cur_xy = self.items[idx]
                        .blocks
                        .get(self.current_block_idx)
                        .map(|b| (b.x, b.y));
                    if cur_xy != Some((nx, ny)) {
                        self.record_undo_before_edit();
                        if let Some(b) = self.items[idx].blocks.get_mut(self.current_block_idx) {
                            b.x = nx;
                            b.y = ny;
                            self.dirty = true;
                            self.needs_rerender = true;
                        }
                    }
                }
            }
        }

        if response.dragged_by(egui::PointerButton::Middle) {
            self.zoom_fit = false;
            self.pan += response.drag_delta();
        }

        if response.drag_stopped() {
            self.dragging_block = None;
            self.dragging_hscroll = false;
            self.dragging_vscroll = false;
            if self.in_edit_gesture {
                self.commit_discrete_edit();
            }
        }

        if !self.zoom_fit {
            if content_w > rect.width() {
                self.pan.x = self.pan.x.clamp(rect.width() - content_w, 0.0);
            } else {
                self.pan.x = ((rect.width() - content_w) * 0.5).max(0.0);
            }
            if content_h > rect.height() {
                self.pan.y = self.pan.y.clamp(rect.height() - content_h, 0.0);
            } else {
                self.pan.y = ((rect.height() - content_h) * 0.5).max(0.0);
            }
        }

        let total_h = if is_hstack {
            max_ph * scale + 30.0
        } else {
            panel_kinds
                .iter()
                .map(|p| p.1[1] as f32 * scale + 30.0)
                .sum::<f32>()
        };
        let start_y = if self.zoom_fit {
            rect.min.y + ((rect.height() - total_h) * 0.5).max(8.0)
        } else {
            rect.min.y + self.pan.y + 8.0
        };
        let mut cur_y = start_y;
        let mut cur_x = if self.zoom_fit || content_w <= rect.width() {
            rect.center().x - (content_w - 28.0) * 0.5
        } else {
            rect.min.x + self.pan.x + 14.0
        };
        self.ren_panel_rect = None;

        let bg_rgba = hex_to_rgba(&self.items[idx].bg_color, [0, 0, 0, 255]);
        let bg_c32 =
            egui::Color32::from_rgba_unmultiplied(bg_rgba[0], bg_rgba[1], bg_rgba[2], bg_rgba[3]);

        for (title, sz, is_ren) in panel_kinds {
            let nw = sz[0] as f32 * scale;
            let nh = sz[1] as f32 * scale;
            let (cx, py) = if is_hstack {
                (cur_x + nw * 0.5, start_y)
            } else {
                let x = if self.zoom_fit || content_w <= rect.width() {
                    rect.center().x
                } else {
                    rect.min.x + self.pan.x + max_pw * scale * 0.5 + 14.0
                };
                (x, cur_y)
            };

            painter.text(
                egui::pos2(cx, py + 8.0),
                egui::Align2::CENTER_CENTER,
                format!("{title} ({}x{})", sz[0], sz[1]),
                egui::FontId::proportional(12.0),
                egui::Color32::from_gray(205),
            );

            let img_rect =
                egui::Rect::from_min_size(egui::pos2(cx - nw * 0.5, py + 20.0), egui::vec2(nw, nh));
            draw_checkerboard_sub(&painter, img_rect, rect.min, self.checker_tex.as_ref());

            if !is_ren {
                if let Some((_, tiled)) = &self.orig_tex {
                    tiled.draw(&painter, img_rect, rect, scale);
                }
            } else {
                self.ren_panel_rect = Some(img_rect);

                // Base: original image if present, else solid bg_color
                if let Some((_, tiled)) = &self.orig_tex {
                    tiled.draw(&painter, img_rect, rect, scale);
                    for &ob in &self.orig_boxes {
                        let hit = self
                            .block_cache
                            .iter()
                            .zip(self.ren_rects.iter())
                            .any(|(c, r)| c.tex.is_some() && rects_overlap(*r, ob, 4));
                        if hit {
                            let e_rect = egui::Rect::from_min_max(
                                img_rect.min
                                    + egui::vec2(
                                        (ob[0] - 2) as f32 * scale,
                                        (ob[1] - 2) as f32 * scale,
                                    ),
                                img_rect.min
                                    + egui::vec2(
                                        (ob[2] + 3) as f32 * scale,
                                        (ob[3] + 3) as f32 * scale,
                                    ),
                            );
                            if bg_rgba[3] < 255 {
                                draw_checkerboard_sub(
                                    &painter,
                                    e_rect,
                                    rect.min,
                                    self.checker_tex.as_ref(),
                                );
                            } else {
                                painter.rect_filled(e_rect, 0.0, bg_c32);
                            }
                        }
                    }
                } else {
                    painter.rect_filled(img_rect, 0.0, bg_c32);
                }

                // Draw each block's tight GPU texture
                let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
                for (c, &[rx0, ry0, rx1, ry1]) in self.block_cache.iter().zip(self.ren_rects.iter())
                {
                    if let Some(tex) = &c.tex {
                        let b_rect = egui::Rect::from_min_max(
                            img_rect.min + egui::vec2(rx0 as f32 * scale, ry0 as f32 * scale),
                            img_rect.min + egui::vec2(rx1 as f32 * scale, ry1 as f32 * scale),
                        );
                        painter.image(tex.id(), b_rect, uv, egui::Color32::WHITE);
                    }
                }
            }

            if self.show_box {
                let cyan = egui::Stroke::new(2.0, egui::Color32::from_rgb(0, 210, 255));
                for (li, &[lx0, ly0, lx1, ly1]) in self.orig_boxes.iter().enumerate() {
                    let b_rect = egui::Rect::from_min_max(
                        img_rect.min + egui::vec2(lx0 as f32 * scale, ly0 as f32 * scale),
                        img_rect.min + egui::vec2(lx1 as f32 * scale, ly1 as f32 * scale),
                    );
                    if b_rect.max.y < rect.min.y || b_rect.min.y > rect.max.y {
                        continue;
                    }
                    painter.rect_stroke(b_rect, 0.0, cyan, egui::StrokeKind::Inside);
                    if !is_ren {
                        painter.text(
                            b_rect.min - egui::vec2(0.0, 12.0),
                            egui::Align2::LEFT_BOTTOM,
                            format!(
                                "L{} ({},{})-({},{}) h={}",
                                li + 1,
                                lx0,
                                ly0,
                                lx1,
                                ly1,
                                ly1 - ly0 + 1
                            ),
                            egui::FontId::proportional(10.0),
                            egui::Color32::from_rgb(0, 230, 255),
                        );
                    }
                }
            }

            if is_ren {
                if self.block_selected {
                    if let Some(&[rx0, ry0, rx1, ry1]) = self.ren_rects.get(self.current_block_idx)
                    {
                        let s_rect = egui::Rect::from_min_max(
                            img_rect.min + egui::vec2(rx0 as f32 * scale, ry0 as f32 * scale),
                            img_rect.min + egui::vec2(rx1 as f32 * scale, ry1 as f32 * scale),
                        );
                        let gold = egui::Color32::from_rgb(255, 215, 0);
                        painter.rect_stroke(
                            s_rect,
                            0.0,
                            egui::Stroke::new(2.0, gold),
                            egui::StrokeKind::Outside,
                        );
                        for corner in [
                            s_rect.left_top(),
                            s_rect.right_top(),
                            s_rect.left_bottom(),
                            s_rect.right_bottom(),
                        ] {
                            painter.rect_filled(
                                egui::Rect::from_center_size(corner, egui::vec2(8.0, 8.0)),
                                0.0,
                                gold,
                            );
                        }
                    }
                }
                if self.show_box || self.block_selected {
                    for (bi, b) in self.items[idx].blocks.iter().enumerate() {
                        let pos = img_rect.min + egui::vec2(b.x as f32 * scale, b.y as f32 * scale);
                        let col = if self.block_selected && bi == self.current_block_idx {
                            egui::Color32::from_rgb(255, 215, 0)
                        } else if bi == self.current_block_idx {
                            egui::Color32::from_rgb(0, 255, 120)
                        } else {
                            egui::Color32::from_rgb(120, 180, 255)
                        };
                        let arm = 20.0 * scale.min(1.5);
                        painter.line_segment(
                            [pos - egui::vec2(arm, 0.0), pos + egui::vec2(arm, 0.0)],
                            egui::Stroke::new(2.0, col),
                        );
                        painter.line_segment(
                            [pos - egui::vec2(0.0, arm), pos + egui::vec2(0.0, arm)],
                            egui::Stroke::new(2.0, col),
                        );
                    }
                }
            }

            if is_hstack {
                cur_x += nw + 20.0;
            } else {
                cur_y += nh + 30.0;
            }
        }

        // Draw scrollbars when zoomed larger than viewport
        if has_h {
            painter.rect_filled(h_track, 3.0, egui::Color32::from_black_alpha(120));
            let frac_w = (rect.width() / content_w).clamp(0.08, 1.0);
            let thumb_w = (h_track.width() * frac_w).max(24.0);
            let max_pan_x = (content_w - rect.width()).max(1.0);
            let t = (-self.pan.x / max_pan_x).clamp(0.0, 1.0);
            let tx = h_track.min.x + t * (h_track.width() - thumb_w);
            let thumb = egui::Rect::from_min_size(
                egui::pos2(tx, h_track.min.y),
                egui::vec2(thumb_w, h_track.height()),
            );
            painter.rect_filled(thumb, 3.0, egui::Color32::from_gray(150));
        }
        if has_v {
            painter.rect_filled(v_track, 3.0, egui::Color32::from_black_alpha(120));
            let frac_h = (rect.height() / content_h).clamp(0.08, 1.0);
            let thumb_h = (v_track.height() * frac_h).max(24.0);
            let max_pan_y = (content_h - rect.height()).max(1.0);
            let t = (-self.pan.y / max_pan_y).clamp(0.0, 1.0);
            let ty = v_track.min.y + t * (v_track.height() - thumb_h);
            let thumb = egui::Rect::from_min_size(
                egui::pos2(v_track.min.x, ty),
                egui::vec2(v_track.width(), thumb_h),
            );
            painter.rect_filled(thumb, 3.0, egui::Color32::from_gray(150));
        }
    }
}

fn draw_checkerboard_sub(
    painter: &egui::Painter,
    rect: egui::Rect,
    origin: egui::Pos2,
    tex: Option<&egui::TextureHandle>,
) {
    if let Some(t) = tex {
        let cell2 = 32.0;
        let u0 = (rect.min.x - origin.x) / cell2;
        let v0 = (rect.min.y - origin.y) / cell2;
        let u1 = (rect.max.x - origin.x) / cell2;
        let v1 = (rect.max.y - origin.y) / cell2;
        painter.image(
            t.id(),
            rect,
            egui::Rect::from_min_max(egui::pos2(u0, v0), egui::pos2(u1, v1)),
            egui::Color32::WHITE,
        );
    } else {
        painter.rect_filled(rect, 0.0, egui::Color32::from_gray(205));
    }
}

fn collect_pngs(root: &Path, dir: &Path, out: &mut Vec<String>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            collect_pngs(root, &p, out);
        } else if p
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.eq_ignore_ascii_case("png"))
            .unwrap_or(false)
        {
            if let Ok(rel) = p.strip_prefix(root) {
                out.push(rel.to_string_lossy().replace('\\', "/"));
            }
        }
    }
}

fn setup_cjk_fonts(ctx: &egui::Context) {
    let candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ];
    for c in candidates {
        if let Ok(bytes) = std::fs::read(c) {
            let mut fonts = egui::FontDefinitions::default();
            fonts.font_data.insert(
                "cjk_ui".to_owned(),
                egui::FontData::from_owned(bytes).into(),
            );
            fonts
                .families
                .entry(egui::FontFamily::Proportional)
                .or_default()
                .insert(0, "cjk_ui".to_owned());
            fonts
                .families
                .entry(egui::FontFamily::Monospace)
                .or_default()
                .push("cjk_ui".to_owned());
            ctx.set_fonts(fonts);
            break;
        }
    }
}
