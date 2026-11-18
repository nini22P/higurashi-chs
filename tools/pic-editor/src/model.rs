use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Align {
    Left,
    Center,
    Right,
}

impl Default for Align {
    fn default() -> Self {
        Self::Center
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Valign {
    Top,
    Middle,
    Bottom,
}

impl Default for Valign {
    fn default() -> Self {
        Self::Middle
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TextBlock {
    #[serde(default = "default_block_name")]
    pub name: String,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub translation: String,
    #[serde(default)]
    pub x: i32,
    #[serde(default)]
    pub y: i32,
    #[serde(default = "default_font")]
    pub font: String,
    #[serde(default = "default_font_size")]
    pub font_size: u32,
    #[serde(default = "default_line_gap")]
    pub line_gap: i32,
    #[serde(default)]
    pub char_gap: i32,
    #[serde(default = "default_blank_height")]
    pub blank_height: i32,
    #[serde(default = "default_scale_x")]
    pub scale_x: f32,
    #[serde(default)]
    pub align: Align,
    #[serde(default)]
    pub valign: Valign,
    #[serde(default = "default_color")]
    pub color: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PicItem {
    pub file: String,
    pub width: u32,
    pub height: u32,
    #[serde(default = "default_bg_color")]
    pub bg_color: String,
    #[serde(default)]
    pub blocks: Vec<TextBlock>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PicConfig {
    #[serde(default)]
    pub fonts: BTreeMap<String, String>,
    #[serde(default)]
    pub items: Vec<PicItem>,
}

fn default_block_name() -> String {
    "main".into()
}
fn default_font() -> String {
    "serif".into()
}
fn default_font_size() -> u32 {
    48
}
fn default_line_gap() -> i32 {
    16
}
fn default_blank_height() -> i32 {
    36
}
fn default_scale_x() -> f32 {
    1.0
}
fn default_color() -> String {
    "#FFFFFF".into()
}
fn default_bg_color() -> String {
    "#000000FF".into()
}

pub fn hex_to_rgba(s: &str, default: [u8; 4]) -> [u8; 4] {
    let trimmed = s.trim();
    if trimmed.eq_ignore_ascii_case("transparent") {
        return [0, 0, 0, 0];
    }
    let hex = trimmed.strip_prefix('#').unwrap_or(trimmed);
    if hex.len() == 6 {
        if let (Ok(r), Ok(g), Ok(b)) = (
            u8::from_str_radix(&hex[0..2], 16),
            u8::from_str_radix(&hex[2..4], 16),
            u8::from_str_radix(&hex[4..6], 16),
        ) {
            return [r, g, b, 255];
        }
    } else if hex.len() == 8 {
        if let (Ok(r), Ok(g), Ok(b), Ok(a)) = (
            u8::from_str_radix(&hex[0..2], 16),
            u8::from_str_radix(&hex[2..4], 16),
            u8::from_str_radix(&hex[4..6], 16),
            u8::from_str_radix(&hex[6..8], 16),
        ) {
            return [r, g, b, a];
        }
    }
    default
}

pub fn rgba_to_hex_rgb(c: [u8; 3]) -> String {
    format!("#{:02X}{:02X}{:02X}", c[0], c[1], c[2])
}

pub fn rgba_to_hex_rgba(c: [u8; 4]) -> String {
    format!("#{:02X}{:02X}{:02X}{:02X}", c[0], c[1], c[2], c[3])
}
