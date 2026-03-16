//! Schema tools: DDL normalization for DuckDB and DuckDB EXPLAIN plan parsing.
//! Used by Python schema_ddl and schema_evaluate; callable via schema_tools binary or from Rust.

use regex::Regex;
use std::collections::HashSet;

/// Normalize PostgreSQL DDL for DuckDB: strip comments, triggers, functions, normalize types.
pub fn ddl_to_duckdb(pg_ddl: &str) -> String {
    let mut out = pg_ddl.to_string();

    // Strip single-line comments
    let re = Regex::new(r"--[^\n]*").unwrap();
    out = re.replace_all(&out, "\n").to_string();

    // Strip block comments
    let re = Regex::new(r"/\*.*?\*/").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip begin/commit
    let re = Regex::new(r"(?i)\bbegin\s*;").unwrap();
    out = re.replace_all(&out, "").to_string();
    let re = Regex::new(r"(?i)\bcommit\s*;").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip set search_path
    let re = Regex::new(r"(?i)set\s+search_path\s*=\s*\w+\s*;").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip create function
    let re = Regex::new(r"(?is)create\s+or\s+replace\s+function\s+[^;]+;").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip drop trigger
    let re = Regex::new(r"(?i)drop\s+trigger\s+if\s+exists\s+[^;]+;").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip create trigger
    let re = Regex::new(r"(?i)create\s+trigger\s+[^;]+;").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Type replacements (word boundaries)
    let re = Regex::new(r"(?i)\btimestamptz\b").unwrap();
    out = re.replace_all(&out, "TIMESTAMP").to_string();
    let re = Regex::new(r"(?i)\bbigserial\b").unwrap();
    out = re.replace_all(&out, "BIGINT").to_string();
    let re = Regex::new(r"(?i)\bserial\b").unwrap();
    out = re.replace_all(&out, "INTEGER").to_string();
    let re = Regex::new(r"(?i)\bjsonb\b").unwrap();
    out = re.replace_all(&out, "JSON").to_string();
    let re = Regex::new(r"(?i)\bboolean\b").unwrap();
    out = re.replace_all(&out, "BOOLEAN").to_string();
    let re = Regex::new(r"(?i)\bsmallint\b").unwrap();
    out = re.replace_all(&out, "SMALLINT").to_string();
    let re = Regex::new(r"(?i)\bdouble\s+precision\b").unwrap();
    out = re.replace_all(&out, "DOUBLE").to_string();

    // Strip on delete clauses
    let re = Regex::new(r"\s+on\s+delete\s+cascade\b").unwrap();
    out = re.replace_all(&out, "").to_string();
    let re = Regex::new(r"\s+on\s+delete\s+set\s+null\b").unwrap();
    out = re.replace_all(&out, "").to_string();
    let re = Regex::new(r"\s+on\s+delete\s+set\s+default\b").unwrap();
    out = re.replace_all(&out, "").to_string();

    // Strip partial index WHERE
    let re = Regex::new(r"(\bcreate\s+index\s+[^;]*?)\s+where\s+[^;]+(\s*;)").unwrap();
    out = re.replace_all(&out, "$1$2").to_string();

    out
}

/// Extract CREATE TABLE and CREATE INDEX statements from DDL.
pub fn extract_statements(ddl: &str) -> Vec<String> {
    let create_table = Regex::new(r"(?i)^create\s+table").unwrap();
    let create_index = Regex::new(r"(?i)^create\s+(unique\s+)?index").unwrap();
    let mut stmts = Vec::new();
    for part in ddl.split(";") {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if create_table.is_match(part) || create_index.is_match(part) {
            stmts.push(format!("{};", part));
        }
    }
    stmts
}

/// Parse DuckDB EXPLAIN text; return (time_ms, plan_summary).
pub fn parse_duckdb_plan(text: &str) -> (Option<f64>, String) {
    let mut time_ms: Option<f64> = None;
    if let Some(caps) = Regex::new(r"(?i)Total\s+Time:\s*([\d.]+)\s*s")
        .unwrap()
        .captures(text)
    {
        if let Some(m) = caps.get(1) {
            if let Ok(t) = m.as_str().parse::<f64>() {
                time_ms = Some(t * 1000.0);
            }
        }
    }
    if time_ms.is_none() {
        if let Some(caps) = Regex::new(r"([\d.]+)\s*ms").unwrap().captures(text) {
            if let Ok(t) = caps.get(1).unwrap().as_str().parse::<f64>() {
                time_ms = Some(t);
            }
        }
    }
    if text.contains("Error:") {
        return (time_ms, "Error".to_string());
    }

    static OPS: &[&str] = &[
        "HASH_JOIN", "TABLE_SCAN", "TOP_N", "ORDER_BY", "PROJECTION", "EMPTY_RESULT", "EXPLAIN_ANALYZE",
    ];
    let op_re = Regex::new(r"\b([A-Z][A-Z0-9_]{2,})\b").unwrap();
    let mut ops: Vec<&str> = op_re
        .find_iter(text)
        .filter_map(|m| {
            let s = m.as_str();
            if OPS.contains(&s) {
                Some(s)
            } else {
                None
            }
        })
        .collect();
    let mut seen = HashSet::new();
    ops.retain(|o| seen.insert(*o));

    let mut labels = Vec::new();
    for op in ops {
        match op {
            "HASH_JOIN" => labels.push("Hash Join".to_string()),
            "TABLE_SCAN" => {
                let tbl = Regex::new(r"memory\.\w+\.(\w+)")
                    .unwrap()
                    .captures(text)
                    .and_then(|c| c.get(1))
                    .map(|m| m.as_str().to_string());
                let seq = text.contains("Sequential Scan") || text.contains("Sequential scan");
                let s = match tbl {
                    Some(t) => {
                        if seq {
                            format!("Table Scan {} (Seq)", t)
                        } else {
                            format!("Table Scan {}", t)
                        }
                    }
                    None => "Table Scan".to_string(),
                };
                labels.push(s);
            }
            "TOP_N" => labels.push("Top-N".to_string()),
            "ORDER_BY" => labels.push("Order By".to_string()),
            "PROJECTION" | "EMPTY_RESULT" | "EXPLAIN_ANALYZE" => {}
            _ => labels.push(op.replace('_', " ").to_string()),
        }
    }
    let plan_summary = if labels.is_empty() {
        "OK".to_string()
    } else {
        labels.into_iter().take(4).collect::<Vec<_>>().join(", ")
    };
    (time_ms, plan_summary)
}
