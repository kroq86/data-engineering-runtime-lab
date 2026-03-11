use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use crate::common::Row;
use crate::product::{TxStagedOp, WalOp};

pub(crate) fn tx_journal_path(journal_dir: &Path, tx_id: u64) -> PathBuf {
    journal_dir.join(format!("tx_{tx_id}.journal"))
}

pub(crate) fn create_tx_journal_file(
    journal_dir: &Path,
    tx_id: u64,
) -> Result<(), String> {
    fs::create_dir_all(journal_dir)
        .map_err(|e| format!("create tx_journal dir failed: {e}"))?;
    File::create(tx_journal_path(journal_dir, tx_id))
        .map_err(|e| format!("create tx journal failed: {e}"))?;
    Ok(())
}

pub(crate) fn append_tx_journal_op(
    journal_dir: &Path,
    tx_id: u64,
    op: &TxStagedOp,
) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open(tx_journal_path(journal_dir, tx_id))
        .map_err(|e| format!("open tx journal failed: {e}"))?;
    let line = match &op.op {
        WalOp::Insert(row) => {
            format!("I,{},{},{}\n", row.order_id, row.customer_id, row.amount)
        }
        WalOp::Upsert(row) => format!(
            "U,{},{},{},{}\n",
            row.order_id,
            row.customer_id,
            row.amount,
            op.observed_version.unwrap_or(0)
        ),
    };
    file.write_all(line.as_bytes())
        .map_err(|e| format!("write tx journal failed: {e}"))
}

pub(crate) fn remove_tx_journal(
    journal_dir: &Path,
    tx_id: u64,
) -> Result<(), String> {
    let path = tx_journal_path(journal_dir, tx_id);
    if path.exists() {
        fs::remove_file(path)
            .map_err(|e| format!("remove tx journal failed: {e}"))?;
    }
    Ok(())
}

pub(crate) fn load_recovery_journals(
    journal_dir: &Path,
) -> Result<HashMap<u64, Vec<TxStagedOp>>, String> {
    let mut out: HashMap<u64, Vec<TxStagedOp>> = HashMap::new();
    if !journal_dir.exists() {
        return Ok(out);
    }
    let entries = fs::read_dir(journal_dir)
        .map_err(|e| format!("read tx_journal directory failed: {e}"))?;
    for entry in entries {
        let entry = entry.map_err(|e| format!("read tx_journal entry failed: {e}"))?;
        let path = entry.path();
        let Some(file_name) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if !file_name.starts_with("tx_") || !file_name.ends_with(".journal") {
            continue;
        }
        let tx_str = file_name
            .trim_start_matches("tx_")
            .trim_end_matches(".journal");
        let tx_id = tx_str
            .parse::<u64>()
            .map_err(|e| format!("parse tx id from journal filename failed: {e}"))?;
        let file = File::open(&path).map_err(|e| format!("open tx journal failed: {e}"))?;
        let reader = BufReader::new(file);
        let mut ops = Vec::<TxStagedOp>::new();
        for line in reader.lines() {
            let line = line.map_err(|e| format!("read tx journal line failed: {e}"))?;
            if line.trim().is_empty() {
                continue;
            }
            ops.push(parse_tx_journal_line(&line)?);
        }
        out.insert(tx_id, ops);
    }
    Ok(out)
}

fn parse_tx_journal_line(line: &str) -> Result<TxStagedOp, String> {
    let parts: Vec<&str> = line.split(',').collect();
    if parts.len() < 4 {
        return Err("invalid tx journal record format".to_string());
    }
    let kind = parts[0].trim();
    let order_id = parts[1]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("tx journal order_id parse failed: {e}"))?;
    let customer_id = parts[2]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("tx journal customer_id parse failed: {e}"))?;
    let amount = parts[3]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("tx journal amount parse failed: {e}"))?;
    let row = Row {
        order_id,
        customer_id,
        amount,
        amount_with_tax: None,
    };
    match kind {
        "I" => Ok(TxStagedOp {
            op: WalOp::Insert(row),
            observed_version: None,
        }),
        "U" => {
            let observed_version = if parts.len() > 4 {
                Some(
                    parts[4]
                        .trim()
                        .parse::<u64>()
                        .map_err(|e| format!("tx journal observed version parse failed: {e}"))?,
                )
            } else {
                Some(0)
            };
            Ok(TxStagedOp {
                op: WalOp::Upsert(row),
                observed_version,
            })
        }
        _ => Err("unknown tx journal operation type".to_string()),
    }
}

pub(crate) fn parse_snapshot_line(line: &str) -> Result<Option<Row>, String> {
    let parts: Vec<&str> = line.split(',').collect();
    if parts.len() != 3 {
        return Ok(None);
    }
    let order_id = parts[0]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("snapshot order_id parse failed: {e}"))?;
    let customer_id = parts[1]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("snapshot customer_id parse failed: {e}"))?;
    let amount = parts[2]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("snapshot amount parse failed: {e}"))?;
    Ok(Some(Row {
        order_id,
        customer_id,
        amount,
        amount_with_tax: None,
    }))
}

pub(crate) fn parse_wal_line(line: &str) -> Result<WalOp, String> {
    let parts: Vec<&str> = line.split(',').collect();
    if parts.len() != 4 {
        return Err("invalid wal record format".to_string());
    }
    let kind = parts[0].trim();
    let order_id = parts[1]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("wal order_id parse failed: {e}"))?;
    let customer_id = parts[2]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("wal customer_id parse failed: {e}"))?;
    let amount = parts[3]
        .trim()
        .parse::<i32>()
        .map_err(|e| format!("wal amount parse failed: {e}"))?;
    let row = Row {
        order_id,
        customer_id,
        amount,
        amount_with_tax: None,
    };
    match kind {
        "I" => Ok(WalOp::Insert(row)),
        "U" => Ok(WalOp::Upsert(row)),
        _ => Err("unknown wal operation type".to_string()),
    }
}
