mod editor;
mod model;
mod render;

use clap::{Parser, Subcommand};
use model::PicConfig;
use rayon::prelude::*;
use render::{render_item, FontCache};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Parser)]
#[command(name = "pic-editor", about = "GUI editor and CLI batch renderer for pic-hou")]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Commands>,

    #[arg(long, default_value = "")]
    json: String,

    #[arg(long, default_value = "")]
    orig_dir: String,

    #[arg(long, default_value = "")]
    font_dir: String,

    #[arg(long, default_value = "")]
    out_dir: String,
}

#[derive(Subcommand)]
enum Commands {
    /// Batch render images from JSON using rayon
    Draw {
        #[arg(long)]
        json: PathBuf,
        #[arg(long)]
        orig_dir: Option<PathBuf>,
        #[arg(long)]
        font_dir: String,
        #[arg(long)]
        out_dir: PathBuf,
        #[arg(long)]
        only: Option<String>,
        #[arg(long)]
        dry_run: bool,
    },
}

fn run_draw(json: PathBuf, orig_dir: Option<PathBuf>, font_dir: String, out_dir: PathBuf, only: Option<String>, dry_run: bool) {
    let txt = std::fs::read_to_string(&json).unwrap_or_else(|e| {
        eprintln!("Failed to read {}: {e}", json.display());
        std::process::exit(1);
    });
    let cfg: PicConfig = serde_json::from_str(&txt).unwrap_or_else(|e| {
        eprintln!("Invalid JSON {}: {e}", json.display());
        std::process::exit(1);
    });

    let only_set: Option<HashSet<String>> = only.map(|s| s.split(',').map(|x| x.trim().to_string()).collect());
    let cache = FontCache::default();
    let rendered = AtomicUsize::new(0);
    let skipped = AtomicUsize::new(0);

    let res: Result<(), String> = cfg.items.par_iter().try_for_each(|item| {
        if let Some(set) = &only_set {
            if !set.contains(&item.file) {
                return Ok(());
            }
        }
        if item.blocks.is_empty() || !item.blocks.iter().any(|b| !b.translation.trim().is_empty()) {
            skipped.fetch_add(1, Ordering::Relaxed);
            return Ok(());
        }
        let orig_img = orig_dir.as_ref().and_then(|dir| {
            let p = dir.join(&item.file);
            image::open(&p).ok().map(|im| im.to_rgba8())
        });
        let (img, _) = render_item(item, &cfg.fonts, &font_dir, orig_img.as_ref(), None, &cache)?;
        if !dry_run {
            let dst = out_dir.join(&item.file);
            if let Some(parent) = dst.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            img.save(&dst).map_err(|e| e.to_string())?;
        }
        rendered.fetch_add(1, Ordering::Relaxed);
        Ok(())
    });

    if let Err(e) = res {
        eprintln!("Error: {e}");
        std::process::exit(1);
    }
    println!(
        "Done: rendered={}, skipped={}",
        rendered.load(Ordering::Relaxed),
        skipped.load(Ordering::Relaxed)
    );
}

fn main() {
    let cli = Cli::parse();
    if let Some(Commands::Draw {
        json,
        orig_dir,
        font_dir,
        out_dir,
        only,
        dry_run,
    }) = cli.cmd
    {
        run_draw(json, orig_dir, font_dir, out_dir, only, dry_run);
        return;
    }

    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("pic-editor")
            .with_maximized(true),
        ..Default::default()
    };

    let json = cli.json;
    let orig_dir = cli.orig_dir;
    let font_dir = cli.font_dir;
    let out_dir = cli.out_dir;

    if let Err(e) = eframe::run_native(
        "pic-editor",
        options,
        Box::new(move |cc| Ok(Box::new(editor::PicEditorApp::new(cc, json, orig_dir, font_dir, out_dir)))),
    ) {
        eprintln!("Failed to start GUI: {e}");
        std::process::exit(1);
    }
}
