use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CsvData {
    headers: Vec<String>,
    rows: Vec<Vec<String>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SaveCsvPayload {
    file_path: String,
    edited_translations: HashMap<usize, String>,
}

fn load_csv_from_path(path: &Path) -> Result<CsvData, String> {
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)
        .map_err(|e| format!("打开 CSV 失败: {e}"))?;

    let headers = reader
        .headers()
        .map_err(|e| format!("读取表头失败: {e}"))?
        .iter()
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();

    let mut rows: Vec<Vec<String>> = Vec::new();
    for record in reader.records() {
        let record = record.map_err(|e| format!("读取记录失败: {e}"))?;
        rows.push(record.iter().map(ToOwned::to_owned).collect::<Vec<_>>());
    }

    Ok(CsvData { headers, rows })
}

fn save_csv_to_path(path: &Path, edited_translations: &HashMap<usize, String>) -> Result<(), String> {
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)
        .map_err(|e| format!("打开 CSV 失败: {e}"))?;

    let headers_record = reader
        .headers()
        .map_err(|e| format!("读取表头失败: {e}"))?
        .clone();

    let headers = headers_record
        .iter()
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();

    let translated_index = headers
        .iter()
        .position(|h| h == "translated")
        .ok_or_else(|| "CSV 缺少 translated 列".to_string())?;

    let temp_path = path.with_extension("csv.tmp");

    {
        let mut writer = csv::WriterBuilder::new()
            .has_headers(true)
            .from_path(&temp_path)
            .map_err(|e| format!("创建临时文件失败: {e}"))?;

        writer
            .write_record(headers.iter())
            .map_err(|e| format!("写入表头失败: {e}"))?;

        for (row_index, record) in reader.records().enumerate() {
            let record = record.map_err(|e| format!("读取记录失败: {e}"))?;
            let mut row = record.iter().map(ToOwned::to_owned).collect::<Vec<_>>();

            if row.len() < headers.len() {
                row.resize(headers.len(), String::new());
            }

            if let Some(edited) = edited_translations.get(&row_index) {
                row[translated_index] = edited.clone();
            }

            writer
                .write_record(row.iter())
                .map_err(|e| format!("写入记录失败: {e}"))?;
        }

        writer.flush().map_err(|e| format!("刷新写入失败: {e}"))?;
    }

    std::fs::rename(&temp_path, path).or_else(|_| {
        std::fs::copy(&temp_path, path)
            .map(|_| ())
            .map_err(|e| format!("覆盖原文件失败: {e}"))
            .and_then(|_| {
                std::fs::remove_file(&temp_path)
                    .map_err(|e| format!("清理临时文件失败: {e}"))
            })
    })?;

    Ok(())
}

#[tauri::command]
async fn load_csv(file_path: String) -> Result<CsvData, String> {
    let path = PathBuf::from(file_path);

    tauri::async_runtime::spawn_blocking(move || {
        if !path.exists() {
            return Err("文件不存在".to_string());
        }

        load_csv_from_path(&path)
    })
    .await
    .map_err(|e| format!("读取任务失败: {e}"))?
}

#[tauri::command]
async fn save_csv(payload: SaveCsvPayload) -> Result<(), String> {
    let path = PathBuf::from(payload.file_path);
    let edits = payload.edited_translations;

    tauri::async_runtime::spawn_blocking(move || {
        if !path.exists() {
            return Err("文件不存在".to_string());
        }

        save_csv_to_path(&path, &edits)
    })
    .await
    .map_err(|e| format!("保存任务失败: {e}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![load_csv, save_csv])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
